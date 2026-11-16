"""Turns a raw `ScenarioSignal` from one of the five analytics engines into a
persisted `Event` (one open incident per dedupe key, updated in place while it
continues), and captures a storage-bounded snapshot plus policy-eligible clips.

Snapshots are attempted for every new event subject to the storage cap. Video
clips retain the suspicious-event severity, cooldown, daily-cap and storage policy.

The clip is written `evidence_post_roll_seconds` AFTER the trigger, so it
contains the lead-up and the aftermath, then attached to the event.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import numpy as np

from app.db.repositories.interfaces import Repositories
from app.schemas.camera import Camera
from app.schemas.event import Event, EventCreate
from app.schemas.settings import ThresholdConfig
from app.services.analytics.signals import ScenarioSignal
from app.services.event_explainer import explain_event
from app.services.evidence_policy import EvidenceBudget, rank
from app.services.evidence_service import RollingClipBuffer, evidence_size_mb, save_clip, save_snapshot
from app.services.notification_service import notify
from app.services.storage_manager import delete_media
from app.ws.manager import manager as ws_manager

logger = logging.getLogger(__name__)

# --- Safety-net rate limiter for brand-new events (updates are never limited).
_MAX_NEW_EVENTS_PER_WINDOW = 10
_RATE_WINDOW_SECONDS = 60.0
_recent_new_event_ts: dict[str, deque] = defaultdict(deque)

_clip_budget = EvidenceBudget()
_bg_tasks: set = set()  # strong refs so fire-and-forget clip tasks aren't garbage-collected


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


def _rate_limited(camera_id: str) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    bucket = _recent_new_event_ts[camera_id]
    bucket.append(now)
    cutoff = now - _RATE_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket) > _MAX_NEW_EVENTS_PER_WINDOW


def _kind(signal: ScenarioSignal) -> str:
    return str(signal.meta.get("kind", ""))


def _with_explanation(meta: dict, **event_fields) -> dict:
    """Returns `meta` plus the plain-language explanation. Pure string work; a failure just leaves the
    explanation out (readers regenerate it), so it can never block event storage."""
    try:
        return {**meta, "explanation": explain_event({**event_fields, "meta": meta})}
    except Exception:
        logger.warning("Could not build event explanation", exc_info=True)
        return meta


def _capture_snapshot(frame: np.ndarray, camera_id: str, event_id: str) -> tuple[str, str | None]:
    """Keep the source incident even when optional evidence encoding fails."""
    try:
        return save_snapshot(frame, camera_id), None
    except Exception as exc:
        logger.warning("Snapshot capture failed for event %s (%s)", event_id, type(exc).__name__, exc_info=True)
        return "", "snapshot_write_failed"


async def _snapshot_decision(th: ThresholdConfig) -> tuple[bool, str]:
    """Snapshots are attempted for every new event; only the global storage cap gates them."""
    try:
        size_mb = await asyncio.to_thread(evidence_size_mb)  # cached; never scans the folder on the event loop
    except Exception as exc:
        logger.warning("Snapshot storage check failed (%s)", type(exc).__name__, exc_info=True)
        return False, "storage_check_failed"
    return (True, "ok") if size_mb < th.storage_max_mb else (False, "storage_cap_reached")


async def _evidence_decision(camera: Camera, signal: ScenarioSignal, severity: str, th: ThresholdConfig,
                             *, storage_ok: bool | None = None) -> tuple[bool, str]:
    """Existing severity, cooldown and daily policy applies to clips only."""
    if storage_ok is None:
        try:
            size_mb = await asyncio.to_thread(evidence_size_mb)
        except Exception as exc:
            logger.warning("Evidence storage check failed for camera %s (%s)", camera.id, type(exc).__name__, exc_info=True)
            return False, "storage_check_failed"
        storage_ok = size_mb < th.storage_max_mb
    return _clip_budget.decide(
        camera_id=camera.id,
        scenario=signal.scenario,
        kind=_kind(signal),
        severity=severity,
        min_severity=th.evidence_min_severity,
        cooldown_seconds=th.evidence_cooldown_seconds,
        max_per_day=th.evidence_max_per_day,
        storage_ok=storage_ok,
    )


async def _attach_clip_later(repos: Repositories, event_id: str, camera_id: str, buf: RollingClipBuffer, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        clip_path = await asyncio.to_thread(save_clip, buf.all_jpegs(), camera_id)
        current = await repos.events.get(event_id)
        if current is None:
            if clip_path:
                await asyncio.to_thread(delete_media, [clip_path])
            return
        meta = {**(current.meta or {}), "clip_evidence": "saved" if clip_path else "failed:clip_unavailable"}
        updated = await repos.events.touch(event_id, **({"clip_path": clip_path} if clip_path else {}), meta=meta)
        if updated is None:  # the event was deleted while we waited - don't leave an orphan file
            if clip_path:
                await asyncio.to_thread(delete_media, [clip_path])
    except Exception:
        logger.warning("Could not attach clip to event %s", event_id, exc_info=True)
        try:
            current = await repos.events.get(event_id)
            if current is not None:
                await repos.events.touch(event_id, meta={**(current.meta or {}),
                    "clip_evidence": "failed:clip_write_failed"})
        except Exception:
            logger.warning("Could not record clip failure for event %s", event_id, exc_info=True)


async def handle_signal(
    repos: Repositories,
    signal: ScenarioSignal,
    camera: Camera,
    frame: np.ndarray,
    clip_buffer: RollingClipBuffer,
    thresholds: ThresholdConfig,
    webhook_url: str,
    event_context: dict[str, str] | None = None,
) -> tuple[Event | None, bool]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=thresholds.dedupe_cooldown_seconds)
    existing = await repos.events.find_open_by_dedupe(signal.dedupe_key, since)

    if existing:
        fields: dict = dict(
            confidence=max(existing.confidence, signal.confidence),
            message=signal.message,
            track_ids=sorted(set(existing.track_ids) | set(signal.track_ids)),
            meta={**existing.meta, **signal.meta, **(event_context or {})},
        )
        escalated = rank(signal.severity_hint) > rank(existing.severity)
        if escalated:
            fields["severity"] = signal.severity_hint
            snapshot_allowed, reason = await _snapshot_decision(thresholds)
            if not existing.snapshot_path:
                if snapshot_allowed:
                    snapshot_path, capture_error = await asyncio.to_thread(_capture_snapshot, frame, camera.id, existing.id)
                    fields["snapshot_path"] = snapshot_path
                    if snapshot_path:
                        fields["meta"] = {**fields["meta"], "evidence": "saved"}
                    else:
                        fields["meta"] = {**fields["meta"], "evidence": f"failed:{capture_error or 'snapshot_write_failed'}"}
                else:
                    fields["meta"] = {**fields["meta"], "evidence": f"not_saved:{reason}"}
            clip_pending = (existing.meta or {}).get("clip_evidence") == "pending"
            if (existing.snapshot_path or fields.get("snapshot_path")) and not existing.clip_path and not clip_pending:
                clip_allowed, _clip_reason = await _evidence_decision(
                    camera, signal, signal.severity_hint, thresholds, storage_ok=snapshot_allowed)
                if clip_allowed:
                    _clip_budget.record(camera.id, signal.scenario, _kind(signal))
                    fields["meta"] = {**fields["meta"], "clip_evidence": "pending"}
                    _spawn(_attach_clip_later(repos, existing.id, camera.id, clip_buffer,
                                              thresholds.evidence_post_roll_seconds))
        fields["meta"] = _with_explanation(
            fields["meta"],
            scenario=existing.scenario, severity=fields.get("severity", existing.severity), confidence=fields["confidence"],
            camera_name=existing.camera_name, zone_name=existing.zone_name, track_ids=fields["track_ids"],
        )
        updated = await repos.events.touch(existing.id, **fields)
        return updated or existing, False

    if _rate_limited(camera.id):
        logger.warning(
            "Rate limit: suppressing a new '%s' event on camera %s (more than %d new events in the last %.0fs). "
            "A detector may be flickering on this feed.",
            signal.scenario, camera.name, _MAX_NEW_EVENTS_PER_WINDOW, _RATE_WINDOW_SECONDS,
        )
        return None, False

    snapshot_allowed, reason = await _snapshot_decision(thresholds)
    clip_allowed, _clip_reason = await _evidence_decision(
        camera, signal, signal.severity_hint, thresholds, storage_ok=snapshot_allowed)
    snapshot_path = ""
    capture_error = None
    if snapshot_allowed:
        snapshot_path, capture_error = await asyncio.to_thread(_capture_snapshot, frame, camera.id, "new-event")
        if snapshot_path and clip_allowed:
            _clip_budget.record(camera.id, signal.scenario, _kind(signal))

    if snapshot_path:
        evidence_state = "saved"
    elif capture_error:
        evidence_state = f"failed:{capture_error}"
    else:
        evidence_state = f"not_saved:{reason}"
    meta = {**signal.meta, **(event_context or {}), "evidence": evidence_state,
            **({"clip_evidence": "pending"} if snapshot_path and clip_allowed else {})}
    if signal.zone is not None:
        meta.setdefault("zone_type", signal.zone.zone_type)
    meta = _with_explanation(
        meta, scenario=signal.scenario, severity=signal.severity_hint, confidence=signal.confidence,
        camera_name=camera.name, zone_name=signal.zone.name if signal.zone else "", track_ids=signal.track_ids,
    )
    data = EventCreate(
        camera_id=camera.id,
        camera_name=camera.name,
        zone_id=signal.zone.id if signal.zone else None,
        zone_name=signal.zone.name if signal.zone else "",
        scenario=signal.scenario,
        severity=signal.severity_hint,
        track_ids=signal.track_ids,
        message=signal.message,
        confidence=signal.confidence,
        snapshot_path=snapshot_path,
        clip_path="",
        meta=meta,
        dedupe_key=signal.dedupe_key,
    )
    event = await repos.events.create(data)
    logger.info(
        "New event %s (%s/%s) on camera %s - snapshot: %s; clip eligible: %s",
        event.id, event.scenario, event.severity, camera.name, "saved" if snapshot_path else reason, clip_allowed,
    )
    if snapshot_path and clip_allowed:
        _spawn(_attach_clip_later(repos, event.id, camera.id, clip_buffer, thresholds.evidence_post_roll_seconds))

    try:
        await notify(event, webhook_url)
    except Exception:
        logger.warning("notify() failed", exc_info=True)

    await ws_manager.broadcast({"type": "new_event", "event": event.model_dump(mode="json")})
    return event, True
