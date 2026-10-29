from __future__ import annotations

import asyncio
import csv
import html
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.event import Event, EventFilter, EventReview
from app.services.storage_manager import delete_media

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
async def list_events(
    camera_id: str | None = None,
    scenario: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
    repos: Repositories = Depends(get_repos),
) -> list[Event]:
    flt = EventFilter(camera_id=camera_id, scenario=scenario, severity=severity, status=status, since=since, limit=limit)
    return await repos.events.list(flt)


@router.delete("")
async def clear_events(camera_id: str | None = None, repos: Repositories = Depends(get_repos)) -> dict:
    """Bulk-deletes events - optionally scoped to one camera - without
    touching cameras, zones or guards. Used by the Dashboard's 'Clear
    events' button to recover from an alert flood."""
    # Delete the snapshot/clip files too - clearing only the rows would leave the
    # media on disk forever (the main source of the storage growth).
    events = await repos.events.list(EventFilter(camera_id=camera_id, limit=200_000))
    media = [p for e in events for p in (e.snapshot_path, e.clip_path) if p]
    files_deleted = await asyncio.to_thread(delete_media, media)
    count = await repos.events.clear(camera_id)
    return {"deleted": count, "media_files_deleted": files_deleted}


@router.get("/{event_id}", response_model=Event)
async def get_event(event_id: str, repos: Repositories = Depends(get_repos)) -> Event:
    event = await repos.events.get(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


_SEV_COLOR = {"critical": "#b91c1c", "high": "#ea580c", "medium": "#ca8a04", "low": "#15803d", "info": "#64748b"}


def _fmt_dt(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S UTC") if d else "-"


@router.get("/{event_id}/report", response_class=HTMLResponse)
async def event_report(event_id: str, repos: Repositories = Depends(get_repos)) -> HTMLResponse:
    """A printable one-page incident report (Print -> Save as PDF). Meant to be handed to a
    branch manager / the police: what happened, the evidence, the AI details and the surrounding events."""
    e = await repos.events.get(event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    esc = html.escape
    kind = str(e.meta.get("kind", "")) or e.scenario
    col = _SEV_COLOR.get(e.severity, "#64748b")
    media = ""
    if e.snapshot_path:
        media += f'<img class="snap" src="/storage/{esc(e.snapshot_path)}" alt="snapshot">'
    if e.clip_path:
        media += f'<video class="clip" src="/storage/{esc(e.clip_path)}" controls></video>'
    if not media:
        media = '<p class="muted">No snapshot/clip was stored for this event (only suspicious events keep media).</p>'

    skip = {"people_in_frame", "individuals", "groups"}
    meta_rows = "".join(
        f"<tr><td>{esc(str(k))}</td><td>{esc(json.dumps(v) if not isinstance(v, str) else v)}</td></tr>"
        for k, v in e.meta.items() if k not in skip
    )
    scene = ""
    if "people_in_frame" in e.meta:
        g = e.meta.get("groups") or []
        scene = (f"{e.meta.get('people_in_frame')} people in view, {e.meta.get('individuals', 0)} alone, "
                 f"groups: {'+'.join(str(x) for x in g) if g else 'none'}")

    related = await repos.events.list(EventFilter(camera_id=e.camera_id, limit=300))
    near = sorted((r for r in related if r.id != e.id and abs((r.created_at - e.created_at).total_seconds()) <= 180),
                  key=lambda r: r.created_at)[:25]
    rel_rows = "".join(
        f'<tr><td>{r.created_at.strftime("%H:%M:%S")}</td><td style="color:{_SEV_COLOR.get(r.severity, "#64748b")};font-weight:700">'
        f"{esc(r.severity.upper())}</td><td>{esc(str(r.meta.get('kind', '')) or r.scenario)}</td><td>{esc(r.message)}</td></tr>"
        for r in near
    ) or '<tr><td colspan="4" class="muted">No other events on this camera within 3 minutes.</td></tr>'

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Incident report {esc(e.id[:8])}</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f1f5f9;color:#0f172a}}
 .page{{max-width:900px;margin:20px auto;background:#fff;padding:28px 34px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.12)}}
 h1{{margin:0;font-size:22px}} h2{{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:#475569;margin:22px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}}
 .badge{{display:inline-block;background:{col};color:#fff;padding:4px 12px;border-radius:99px;font-weight:700;font-size:13px}}
 .head{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid {col};padding-bottom:12px}}
 table{{width:100%;border-collapse:collapse;font-size:13px}} td{{padding:5px 8px;border-bottom:1px solid #eef2f7;vertical-align:top}} td:first-child{{color:#64748b;width:30%}}
 .snap,.clip{{max-width:100%;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px}} .muted{{color:#94a3b8}}
 .msg{{font-size:16px;margin:14px 0}} .btn{{background:#0f172a;color:#fff;border:0;padding:8px 16px;border-radius:6px;cursor:pointer}}
 .foot{{margin-top:24px;font-size:11px;color:#94a3b8}} @media print{{body{{background:#fff}} .page{{box-shadow:none;margin:0}} .btn{{display:none}}}}
</style></head><body><div class="page">
 <div class="head"><div><h1>Security Incident Report</h1><div class="muted">Event {esc(e.id)}</div></div>
 <div style="text-align:right"><span class="badge">{esc(e.severity.upper())}</span><br><button class="btn" onclick="window.print()">Print / Save as PDF</button></div></div>
 <p class="msg">{esc(e.message)}</p>
 <h2>Evidence</h2>{media}
 <h2>Summary</h2><table>
  <tr><td>Detected</td><td>{_fmt_dt(e.created_at)}</td></tr><tr><td>Last update</td><td>{_fmt_dt(e.updated_at)}</td></tr>
  <tr><td>Camera</td><td>{esc(e.camera_name)}</td></tr><tr><td>Zone</td><td>{esc(e.zone_name or '-')}</td></tr>
  <tr><td>Incident type</td><td>{esc(kind)}</td></tr><tr><td>Category</td><td>{esc(e.scenario)}</td></tr>
  <tr><td>AI confidence</td><td>{e.confidence:.0%}</td></tr><tr><td>People tracked</td><td>{esc(', '.join('#' + str(t) for t in e.track_ids) or '-')}</td></tr>
  <tr><td>Scene at the time</td><td>{esc(scene or '-')}</td></tr><tr><td>Review status</td><td>{esc(e.status)}</td></tr>
  <tr><td>Reviewer remarks</td><td>{esc(e.reviewer_remarks or '-')}</td></tr></table>
 <h2>AI details</h2><table>{meta_rows or '<tr><td colspan="2" class="muted">-</td></tr>'}</table>
 <h2>Other events on this camera within 3 minutes</h2><table>{rel_rows}</table>
 <p class="foot">Generated by Branch Exterior Monitoring &amp; Anomaly Detection. Alerts are AI-assisted indications and must be verified by a person before any action is taken.</p>
</div></body></html>"""
    return HTMLResponse(page)


@router.post("/{event_id}/review", response_model=Event)
async def review_event(event_id: str, payload: EventReview, repos: Repositories = Depends(get_repos)) -> Event:
    event = await repos.events.review(event_id, payload.status, payload.reviewer_remarks)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.get("/export/csv")
async def export_csv(
    camera_id: str | None = None,
    scenario: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 5000,
    repos: Repositories = Depends(get_repos),
):
    flt = EventFilter(camera_id=camera_id, scenario=scenario, severity=severity, status=status, since=since, limit=limit)
    events = await repos.events.list(flt)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at", "camera", "zone", "scenario", "severity", "status", "confidence", "message"])
    for e in events:
        writer.writerow([e.id, e.created_at.isoformat(), e.camera_name, e.zone_name, e.scenario, e.severity, e.status, e.confidence, e.message])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events_export.csv"},
    )