"""Turns a raw `ScenarioSignal` from one of the five analytics engines into a
persisted `Event` (one open incident per dedupe key, updated in place while it
continues), and decides whether that event earns a snapshot + clip.

Evidence policy (see evidence_policy.py): media is stored ONLY for suspicious
events - high/critical severity, or weapon / fighting - and is rate-limited by
a per-camera cooldown, a daily cap and a storage cap. Everything else is still
recorded as an event row, just without media.

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
from app.services.alert_publisher import get_alert_publisher
from app.services.analytics.signals import ScenarioSignal
from app.services.evidence_policy import EvidenceBudget, is_suspicious, rank
from app.services.evidence_service import RollingClipBuffer, evidence_size_mb, save_clip, save_snapshot
from app.services.notification_service import notify
from app.services.storage_manager import delete_media
from app.ws.manager import manager as ws_manager

logger = logging.getLogger(__name__)

# --- Safety-net rate limiter for brand-new events (updates are never limited).
_MAX_NEW_EVENTS_PER_WINDOW = 10
_RATE_WINDOW_SECONDS = 60.0
_recent_new_event_ts: dict[str, deque] = defaultdict(deque)

_budget = EvidenceBudget()
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


async def _evidence_decision(camera: Camera, signal: ScenarioSignal, severity: str, th: ThresholdConfig) -> tuple[bool, str]:
    size_mb = await asyncio.to_thread(evidence_size_mb)  # cached; never scans the folder on the event loop
    return _budget.decide(
        camera_id=camera.id,
        scenario=signal.scenario,
        kind=_kind(signal),
        severity=severity,
        min_severity=th.evidence_min_severity,
        cooldown_seconds=th.evidence_cooldown_seconds,
        max_per_day=th.evidence_max_per_day,
        storage_ok=size_mb < th.storage_max_mb,
    )


async def _attach_clip_later(repos: Repositories, event_id: str, camera_id: str, buf: RollingClipBuffer, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        clip_path = await asyncio.to_thread(save_clip, buf.all_jpegs(), camera_id)
        if not clip_path:
            return
        updated = await repos.events.touch(event_id, clip_path=clip_path)
        if updated is None:  # the event was deleted while we waited - don't leave an orphan file
            await asyncio.to_thread(delete_media, [clip_path])
    except Exception:
        logger.warning("Could not attach clip to event %s", event_id, exc_info=True)


async def handle_signal(
    repos: Repositories,
    signal: ScenarioSignal,
    camera: Camera,
    frame: np.ndarray,
    clip_buffer: RollingClipBuffer,
    thresholds: ThresholdConfig,
    webhook_url: str,
) -> tuple[Event | None, bool]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=thresholds.dedupe_cooldown_seconds)
    existing = await repos.events.find_open_by_dedupe(signal.dedupe_key, since)

    if existing:
        fields: dict = dict(
            confidence=max(existing.confidence, signal.confidence),
            message=signal.message,
            track_ids=sorted(set(existing.track_ids) | set(signal.track_ids)),
            meta={**existing.meta, **signal.meta},
        )
        escalated = rank(signal.severity_hint) > rank(existing.severity)
        if escalated:
            fields["severity"] = signal.severity_hint
            # An event that started as e.g. "medium" and has now become suspicious
            # earns evidence at that moment (and only then).
            if not existing.snapshot_path:
                allowed, reason = await _evidence_decision(camera, signal, signal.severity_hint, thresholds)
                if allowed:
                    fields["snapshot_path"] = await asyncio.to_thread(save_snapshot, frame, camera.id)
                    _budget.record(camera.id, signal.scenario, _kind(signal))
                    fields["meta"] = {**fields["meta"], "evidence": "saved"}
                    _spawn(
                        _attach_clip_later(repos, existing.id, camera.id, clip_buffer, thresholds.evidence_post_roll_seconds)
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

    allowed, reason = await _evidence_decision(camera, signal, signal.severity_hint, thresholds)
    snapshot_path = ""
    if allowed:
        snapshot_path = await asyncio.to_thread(save_snapshot, frame, camera.id)
        _budget.record(camera.id, signal.scenario, _kind(signal))

    meta = {**signal.meta, "evidence": "saved" if allowed else f"not_saved:{reason}"}
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
        "New event %s (%s/%s) on camera %s - evidence: %s",
        event.id, event.scenario, event.severity, camera.name, "saved" if allowed else reason,
    )
    if allowed:
        _spawn(_attach_clip_later(repos, event.id, camera.id, clip_buffer, thresholds.evidence_post_roll_seconds))

    try:
        await notify(event, webhook_url)
    except Exception:
        logger.warning("notify() failed", exc_info=True)

    try:  # one-way, durable Alert Service publication; never blocks or fails the detection pipeline
        await get_alert_publisher().enqueue(event)
    except Exception:
        logger.warning("Alert Service enqueue failed for event %s", event.id, exc_info=True)

    await ws_manager.broadcast({"type": "new_event", "event": event.model_dump(mode="json")})
    return event, True
