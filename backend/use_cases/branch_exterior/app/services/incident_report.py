"""Builds the printable incident report (HTML) for one event.

The wording comes from `event_explainer`, the same source the Security Brief uses, so the table and the report
always tell the same story. Anything the event data does not contain is shown as "Not available" rather than
guessed. Raw detector details are kept in a collapsed technical appendix for developers only.
"""
from __future__ import annotations

import html
import json
from typing import Any

from app.services.event_explainer import get_explanation, verification_label

NA = "Not available"
_SEV_COLOR = {"critical": "#b91c1c", "high": "#ea580c", "medium": "#ca8a04", "low": "#15803d", "info": "#64748b"}
_HIDDEN_META = {"explanation", "people_in_frame", "individuals", "groups"}

_CSS = """
 body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f1f5f9;color:#0f172a}
 .page{max-width:900px;margin:20px auto;background:#fff;padding:28px 34px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.12)}
 h1{margin:0;font-size:22px} h2{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:#475569;margin:22px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}
 .badge{display:inline-block;color:#fff;padding:4px 12px;border-radius:99px;font-weight:700;font-size:13px}
 .head{display:flex;justify-content:space-between;align-items:center;padding-bottom:12px}
 table{width:100%;border-collapse:collapse;font-size:13px} td{padding:5px 8px;border-bottom:1px solid #eef2f7;vertical-align:top} td:first-child{color:#64748b;width:30%}
 p{line-height:1.5;margin:6px 0} .snap,.clip{max-width:100%;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:8px} .muted{color:#94a3b8}
 .status{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;font-weight:600}
 .btn{background:#0f172a;color:#fff;border:0;padding:8px 16px;border-radius:6px;cursor:pointer}
 .foot{margin-top:24px;font-size:11px;color:#94a3b8} details{margin-top:18px;font-size:12px;color:#475569}
 @media print{body{background:#fff} .page{box-shadow:none;margin:0} .btn{display:none}}
"""


def _fmt_dt(d: Any) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S UTC") if d else NA


def _duration(e: Any) -> str:
    if not (e.created_at and e.updated_at):
        return NA
    s = int((e.updated_at - e.created_at).total_seconds())
    if s < 5:
        return "Single observation"
    return f"{s} seconds" if s < 120 else f"about {round(s / 60)} minutes"


def _rows(pairs: list[tuple[str, str]]) -> str:
    esc = html.escape
    return "<table>" + "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in pairs) + "</table>"


def _media(e: Any) -> str:
    esc = html.escape
    out = ""
    if e.snapshot_path:
        out += f'<img class="snap" src="/storage/{esc(e.snapshot_path)}" alt="Snapshot of the incident">'
    if e.clip_path:
        out += f'<video class="clip" src="/storage/{esc(e.clip_path)}" controls></video>'
    return out or '<p class="muted">No snapshot or video clip was stored for this incident (only suspicious events keep media).</p>'


def _related(e: Any, related: list[Any]) -> str:
    esc = html.escape
    near = sorted((r for r in related if r.id != e.id and abs((r.created_at - e.created_at).total_seconds()) <= 180),
                  key=lambda r: r.created_at)[:25]
    if not near:
        return '<p class="muted">No other events on this camera within 3 minutes.</p>'
    rows = "".join(
        f'<tr><td>{r.created_at.strftime("%H:%M:%S")}</td><td style="color:{_SEV_COLOR.get(r.severity, "#64748b")};font-weight:700">'
        f"{esc(r.severity.upper())}</td><td>{esc(get_explanation(r)['title'])}</td></tr>"
        for r in near
    )
    return f"<table>{rows}</table>"


def _appendix(e: Any) -> str:
    esc = html.escape
    meta = {k: v for k, v in e.meta.items() if k not in _HIDDEN_META}
    rows = "".join(f"<tr><td>{esc(str(k))}</td><td>{esc(v if isinstance(v, str) else json.dumps(v))}</td></tr>" for k, v in meta.items())
    return (
        "<details><summary>Technical appendix (for developers)</summary>"
        f"<table><tr><td>Event ID</td><td>{esc(e.id)}</td></tr><tr><td>Detector message</td><td>{esc(e.message or NA)}</td></tr>"
        f"<tr><td>Tracked IDs</td><td>{esc(', '.join('#' + str(t) for t in e.track_ids) or NA)}</td></tr>"
        f"<tr><td>Raw confidence</td><td>{e.confidence:.2f}</td></tr>{rows}</table></details>"
    )


def build_incident_report(e: Any, related: list[Any]) -> str:
    esc = html.escape
    x = get_explanation(e)
    col = _SEV_COLOR.get(e.severity, "#64748b")
    ver = verification_label(e.status)
    reliability = f"{x['reliability'].capitalize()} ({e.confidence:.0%})"
    caution = f"<p><b>Note:</b> {esc(x['caution'])}</p>" if x["caution"] else ""
    remarks = esc(e.reviewer_remarks) if e.reviewer_remarks else ""

    overview = _rows([
        ("Incident title", x["title"]), ("Incident ID", e.id[:8].upper()), ("Event category", x["category"].replace("_", " ").capitalize()),
        ("Severity", e.severity.upper()), ("Incident date", e.created_at.strftime("%Y-%m-%d") if e.created_at else NA),
        ("Incident time", e.created_at.strftime("%H:%M:%S UTC") if e.created_at else NA), ("Branch", NA),
        ("Camera", e.camera_name or NA), ("Monitored zone", e.zone_name or NA),
    ])
    evidence = _rows([
        ("Detected at", _fmt_dt(e.created_at)), ("Last observed", _fmt_dt(e.updated_at)), ("Duration", _duration(e)),
        ("Camera", e.camera_name or NA), ("Zone", e.zone_name or NA), ("Detection reliability", reliability),
        ("Snapshot", "Attached below" if e.snapshot_path else NA), ("Video clip", "Attached below" if e.clip_path else NA),
    ])
    conclusion = (
        "The activity was flagged by the AI monitoring system and has not been verified. "
        + ("Further review is recommended: the detection reliability is low, so a person should check the footage before drawing conclusions."
           if x["reliability"] == "low" else "A person should review the footage to decide whether further investigation is needed.")
        if e.status == "open" else
        f"Current status: {ver}. " + ("No further action is needed." if e.status in ("false_positive", "closed")
                                      else "Follow-up should continue per the recommended action above.")
    )

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Incident report {esc(e.id[:8])}</title><style>{_CSS}</style></head>
<body><div class="page">
 <div class="head" style="border-bottom:3px solid {col}"><div><h1>Security Incident Report</h1><div class="muted">{esc(x['title'])}</div></div>
 <div style="text-align:right"><span class="badge" style="background:{col}">{esc(e.severity.upper())}</span><br><button class="btn" onclick="window.print()">Print / Save as PDF</button></div></div>
 <h2>1. Incident overview</h2>{overview}
 <h2>2. Incident summary</h2><p>{esc(x['observation'])} {esc(x['reason'])}</p>{caution}
 <h2>3. What the AI observed</h2><p>{esc(x['observation'])}</p>
 <h2>4. Reason for alert</h2><p>{esc(x['reason'])}</p><p class="muted">{esc(x['severity_basis'])}</p>
 <h2>5. Evidence and supporting information</h2>{evidence}{_media(e)}
 <h3 style="font-size:13px;margin:14px 0 4px">Other events on this camera within 3 minutes</h3>{_related(e, related)}
 <h2>6. Risk assessment</h2><p>{esc(x['risk'])} The available evidence does not establish anyone's identity or intention.</p>
 <h2>7. Recommended security action</h2><p>{esc(x['action'])}</p>
 <h2>8. Verification status</h2><p class="status">{esc(ver)}</p>{f'<p>Reviewer remarks: {remarks}</p>' if remarks else ''}
 <h2>9. Conclusion</h2><p>{esc(conclusion)}</p>
 {_appendix(e)}
 <p class="foot">Generated by Branch Exterior Monitoring &amp; Anomaly Detection. Alerts are AI-assisted indications and must be verified by a person before any action is taken.</p>
</div></body></html>"""
