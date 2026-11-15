"""Transactional Grill Gate publication records using the existing shared audit outbox."""
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import object_session
from app.db.models.vault_room import VaultAuditEvent
from grill_gate_monitoring.models.alert import GrillGateAlert
from fedbank_core.events.metadata import enrich_resource_refs, safe_reference
from fedbank_core.events.evidence import evidence_metadata

ENTITY = "grill_gate_alert_delivery"
PENDING, DELIVERED, FAILED = "GRILL_ALERT_PENDING", "GRILL_ALERT_DELIVERED", "GRILL_ALERT_FAILED"


def _configured_camera_metadata(row, refs):
    """Resolve only explicit Gate registry identities; never infer a camera or branch."""
    db = object_session(row)
    if db is None or not row.camera_id:
        return refs
    from app.db.models.camera_registry import RegistryCamera, RegistryLocation
    camera = db.get(RegistryCamera, str(row.camera_id))
    if camera is None:
        return refs
    refs.setdefault("registry_camera_id", str(camera.id))
    if name := safe_reference(camera.name):
        refs.setdefault("camera_name", name)
    refs.setdefault("location_id", str(camera.location_id))
    location = db.get(RegistryLocation, str(camera.location_id))
    if location is not None and (name := safe_reference(location.name)):
        refs.setdefault("location_name", name)
    return refs

def public_payload(row):
    iso = lambda value: value.isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    domain = dict(row.domain_data or {})
    domain["evidence_status"] = domain.get("evidence_status", "UNAVAILABLE")
    domain["lifecycle_owner"] = "source"
    if row.status != 'OPEN' and domain.get('lifecycle_actor_type') != 'operator':
        # A persisted legacy disposition is history, not a new recovery command.
        domain['historical_reconciliation'] = True
    domain["source_status_changed_at"] = iso(row.updated_at or row.triggered_at)
    if row.resolution_note:
        domain["resolution_note"] = row.resolution_note
    refs = dict(row.resource_refs or {})
    for key in ("camera_id", "assignment_id", "video_job_id"):
        if getattr(row, key):
            refs[key] = str(getattr(row, key))
    for key in ("template_assignment_id", "source_id", "source_type", "branch_id", "branch_code", "branch_name",
                "place_name", "region_name", "branch_manager", "camera_name", "video_filename"):
        if (value := safe_reference(domain.get(key))):
            refs.setdefault(key, value)
    if row.camera_name:
        refs["camera_name"] = row.camera_name
    refs = _configured_camera_metadata(row, refs)
    refs = enrich_resource_refs("grill_gate", refs)
    evidence = []
    if row.evidence_refs:
        from grill_gate_monitoring.services.alert_evidence import get_grill_gate_evidence
        for ref in row.evidence_refs:
            try:
                path = get_grill_gate_evidence().path(ref.get('storage_id', ref.get('id')))
                if path.is_file() and path.stat().st_size:
                    evidence.append(ref)
            except (ValueError, TypeError, AttributeError, OSError):
                continue
    domain.update(evidence_metadata(evidence, domain.get('evidence_status') == 'PENDING'))
    return {"schema_version": 1, "source_event_id": row.source_event_id,
        "source_event_type": row.source_event_type, "source_event_version": row.source_event_version,
        "category": row.category, "occurred_at": iso(row.occurred_at),
        "first_seen_at": iso(row.condition_since or row.occurred_at), "last_seen_at": iso(row.triggered_at),
        "severity": row.severity, "title": row.title, "summary": row.summary or row.title,
        "deduplication_key": row.deduplication_key, "source_status": row.status,
        "resource_refs": refs, "domain_data": domain, "evidence_refs": evidence}

def stage_publication(db, row):
    db.flush()
    identity = str(uuid5(NAMESPACE_URL, f"grill-delivery:{row.source_event_id}:{row.source_event_version}"))
    existing = db.get(VaultAuditEvent, identity)
    if existing:
        return existing
    delivery = VaultAuditEvent(id=identity, entity_type=ENTITY, entity_id=row.id, action=PENDING,
        details={"payload": public_payload(row), "attempt": 0, "due_at": datetime.now(timezone.utc).isoformat()})
    db.add(delivery)
    return delivery

def backfill_publications(db, *, limit=100, dry_run=True, offset=0):
    """Explicit operator-controlled backfill. Never fabricate historical snapshots."""
    rows = db.scalars(select(GrillGateAlert).order_by(GrillGateAlert.created_at, GrillGateAlert.id).offset(offset).limit(limit)).all()
    missing = []
    for row in rows:
        identity = str(uuid5(NAMESPACE_URL, f"grill-delivery:{row.source_event_id}:{row.source_event_version}"))
        prior = db.get(VaultAuditEvent, identity)
        if prior is None or prior.action == FAILED:
            missing.append(row.id)
            if not dry_run:
                delivery = stage_publication(db, row)
                delivery.action = PENDING
                delivery.details = {"payload": public_payload(row), "attempt": 0,
                                    "due_at": datetime.now(timezone.utc).isoformat()}
    if not dry_run:
        db.commit()
    return {"dry_run": dry_run, "scanned": len(rows), "eligible": len(missing), "alert_ids": missing, "next_offset": offset + len(rows) if len(rows) == limit else None}
