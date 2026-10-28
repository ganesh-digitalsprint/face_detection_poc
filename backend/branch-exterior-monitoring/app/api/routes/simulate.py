"""Instantly manufactures a realistic-looking event for demo purposes.

Useful when presenting the POC without a live camera pointed at an actual
incident: picks (or is told) a camera and scenario, renders a labelled
placeholder snapshot, and pushes it through the same event-creation and
websocket-broadcast path a real detection would use, so the Dashboard, the
alert ticker and the review workflow can all be demonstrated on demand.
"""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.event import Event, EventCreate, SCENARIO_LABELS
from app.services.evidence_service import draw_placeholder_frame, save_snapshot
from app.services.notification_service import notify
from app.services import db_config_service
from app.ws.manager import manager as ws_manager

router = APIRouter(prefix="/simulate", tags=["simulate"])

_SCENARIO_MESSAGES = {
    "loitering": "Simulated: person lingering near the entrance for 15 minutes after hours.",
    "gathering": "Simulated: 8 people gathered at the entrance at 01:00.",
    "movement": "Simulated: repeated approach to the side door detected.",
    "intrusion": "Simulated: person entered the restricted rear lane while closed.",
    "anomaly": "Simulated: weapon-like object detected, held by tracked person.",
}
_SCENARIO_SEVERITY = {
    "loitering": "high", "gathering": "high", "movement": "medium", "intrusion": "critical", "anomaly": "critical",
}


class SimulateRequest(BaseModel):
    camera_id: str
    scenario: str = "anomaly"


@router.post("/alert", response_model=Event)
async def simulate_alert(payload: SimulateRequest, repos: Repositories = Depends(get_repos)) -> Event:
    camera = await repos.cameras.get(payload.camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if payload.scenario not in SCENARIO_LABELS:
        raise HTTPException(400, f"Unknown scenario '{payload.scenario}'")

    message = _SCENARIO_MESSAGES.get(payload.scenario, "Simulated demo alert.")
    severity = _SCENARIO_SEVERITY.get(payload.scenario, "medium")
    frame = draw_placeholder_frame(
        ["SIMULATED ALERT", SCENARIO_LABELS[payload.scenario], camera.name, message[:48]]
    )
    snapshot_path = save_snapshot(frame, camera.id)

    data = EventCreate(
        camera_id=camera.id, camera_name=camera.name, zone_id=None, zone_name="",
        scenario=payload.scenario, severity=severity, track_ids=[random.randint(1, 99)],
        message=message, confidence=0.9, snapshot_path=snapshot_path, clip_path="",
        meta={"simulated": True}, dedupe_key=f"simulated:{camera.id}:{payload.scenario}:{random.randint(0, 10_000)}",
    )
    event = await repos.events.create(data)
    runtime_cfg = db_config_service.load_runtime_config()
    await notify(event, runtime_cfg.notifications.webhook_url)
    await ws_manager.broadcast({"type": "new_event", "event": event.model_dump(mode="json")})
    return event
