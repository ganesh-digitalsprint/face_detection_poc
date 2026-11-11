"""Bounded source-frame handoff and private, durable Grill Gate JPEG evidence."""
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid5, NAMESPACE_URL
import os
import json
import cv2
from app.core.config import settings
from app.core.ml_config import load_ml_config_file
from app.services.cloudinary_evidence import validate_image
from app.db.models import GrillGateVideoJob

class GrillGateEvidence:
    def __init__(self, root=None, max_frames=8):
        self.root = Path(root or settings.EVIDENCE_SPOOL_DIR).resolve() / "grill-gate-snapshots"
        self.max_frames = max_frames
        self._frames = OrderedDict()
        self._lock = Lock()

    def remember(self, source_id, packet):
        if packet is None or getattr(packet, "frame", None) is None:
            return
        with self._lock:
            if source_id in self._frames:
                return
            self._frames[source_id] = (packet.frame.copy(), {
                "captured_at": packet.captured_at.isoformat(),
                "video_timestamp_seconds": getattr(packet, "video_time_seconds", None),
                "frame_index": packet.sequence_number})
            while len(self._frames) > self.max_frames:
                self._frames.popitem(last=False)

    def path(self, evidence_id):
        # Only deterministic opaque IDs are accepted. No caller-supplied paths.
        from uuid import UUID
        identifier = str(UUID(evidence_id))
        path = self.root / f"{identifier}.jpg"
        if path.resolve().parent != self.root:
            raise ValueError("Invalid evidence identity")
        return path

    def capture(self, db, row):
        evidence_id = str(uuid5(NAMESPACE_URL, f"grill-evidence:{row.source_event_id}"))
        path = self.path(evidence_id)
        sidecar = path.with_suffix(".json")
        if sidecar.resolve().parent != self.root:
            raise ValueError("Invalid evidence metadata identity")
        if path.is_file() and sidecar.is_file() and sidecar.stat().st_size <= 65536:
            ref = json.loads(sidecar.read_text(encoding="utf-8"))
            image = validate_image(path.read_bytes(), "image/jpeg")
            if (ref.get("source_event_id") == row.source_event_id and ref.get("id") == evidence_id
                    and ref.get("checksum") == image.checksum
                    and ref.get("video_job_id") == row.video_job_id
                    and ref.get("assignment_id") == row.assignment_id):
                return ref
        with self._lock:
            buffered = self._frames.pop(row.source_event_id, None)
        frame, metadata = buffered if buffered else (None, {})
        if frame is None and row.video_job_id:
            job = db.get(GrillGateVideoJob, row.video_job_id)
            timestamp = (row.domain_data or {}).get("video_time_seconds")
            if job and isinstance(timestamp, (int, float)) and timestamp >= 0:
                from grill_gate_monitoring.services.video_jobs import read_frame_at
                frame, info = read_frame_at(Path(job.storage_path), timestamp, return_metadata=True)
                decoded = info.get("decoded_seconds_approx")
                metadata = {"requested_video_timestamp_seconds": timestamp,
                    "video_timestamp_seconds": decoded, "frame_index": info.get("frame_index"),
                    "captured_at": row.triggered_at.isoformat()}
        if frame is None:
            raise ValueError("SOURCE_FRAME_UNAVAILABLE")
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("JPEG_ENCODING_FAILED")
        data = encoded.tobytes()
        if len(data) > settings.EVIDENCE_MAX_UPLOAD_BYTES:
            raise ValueError("EVIDENCE_TOO_LARGE")
        image = validate_image(data, "image/jpeg")
        evidence_id = str(uuid5(NAMESPACE_URL, f"grill-evidence:{row.source_event_id}"))
        path = self.path(evidence_id)
        self.root.mkdir(parents=True, exist_ok=True)
        limits = load_ml_config_file().vault_alerts.evidence
        with self._lock:
            if not path.exists():
                files = list(self.root.glob("*.jpg"))
                if len(files) >= limits.spool_max_files or sum(p.stat().st_size for p in files) + len(data) > limits.spool_max_bytes:
                    raise ValueError("EVIDENCE_CAPACITY_REACHED")
                temporary = path.with_suffix(".tmp")
                try:
                    with temporary.open("wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
        scope = ({"video_job_id": row.video_job_id} if row.video_job_id else {"assignment_id": row.assignment_id})
        from urllib.parse import urlencode
        ref = {"id": evidence_id, "type": "snapshot", "provider": "grill_gate", "content_type": "image/jpeg",
            "storage_id": evidence_id, "checksum": image.checksum, "width": image.width, "height": image.height,
            "source_event_id": row.source_event_id, **scope, **metadata,
            "retrieval_path": f"/api/v1/grill-gate/alerts/{row.id}/evidence/{evidence_id}?{urlencode(scope)}"}
        metadata_temp = sidecar.with_suffix(".json.tmp")
        try:
            with metadata_temp.open("w", encoding="utf-8") as handle:
                json.dump(ref, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(metadata_temp, sidecar)
        finally:
            metadata_temp.unlink(missing_ok=True)
        return ref

_evidence = None
def get_grill_gate_evidence():
    global _evidence
    if _evidence is None:
        _evidence = GrillGateEvidence()
    return _evidence
