"""Builds the "Security Brief": a one-page summary of what happened over the last N hours.

Pure Python on a list of events (no web framework, no database) so it is easy to test.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services.event_explainer import get_explanation, verification_label

SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

KIND_LABEL = {
    "weapon": "Weapon-like object", "fighting": "Fighting", "violent_action": "Violent action", "snatch_flee": "Snatch and flee",
    "vehicle_escape": "Escape on a bike", "vehicle_takeoff": "Parked bike taken", "climbing": "Climbing",
    "drop_from_height": "Jump down from height", "fallen": "Person down", "running": "Running", "jumping": "Jumping",
    "scanning": "Lookout behaviour", "gate_tampering": "Gate tampering", "unattended_bag": "Unattended bag",
    "atm_group": "Group at ATM", "group": "Group together", "zone_group": "Group at a zone", "zone_watching": "Staring at a zone",
    "zone_rush": "Running toward a zone", "zone_tamper": "Hands working on a zone", "zone_touch": "Restricted zone breach",
    "zone_near": "Near a restricted zone", "loitering": "Loitering", "gathering": "Gathering", "movement": "Unusual movement",
    "intrusion": "Intrusion", "anomaly": "Anomaly",
}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _kind(e) -> str:
    return str((e.meta or {}).get("kind") or e.scenario)


def _label(kind: str) -> str:
    return KIND_LABEL.get(kind, kind.replace("_", " ").capitalize())


def _iso(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _incident_row(e) -> dict:
    """One Security Brief table row. `message` is the raw technical text, kept for API compatibility;
    the UI shows `observation` (plain language, same text the incident report uses)."""
    x = get_explanation(e)
    return {"id": e.id, "time": _iso(e.created_at), "camera": e.camera_name, "zone": e.zone_name, "kind": _kind(e),
            "label": _label(_kind(e)), "severity": e.severity, "message": e.message, "has_media": bool(e.snapshot_path or e.clip_path),
            "title": x["title"], "observation": x["observation"], "caution": x["caution"], "reliability": x["reliability"],
            "status": e.status, "verification": verification_label(e.status)}


def build_brief(events: list, hours: int, now: datetime | None = None) -> dict:
    now = _utc(now or datetime.now(timezone.utc))
    since = now - timedelta(hours=hours)
    evs = [e for e in events if _utc(e.created_at) >= since]
    high = lambda e: SEV_RANK.get(e.severity, 0) >= 3  # noqa: E731

    by_kind: dict[str, dict] = {}
    for e in evs:
        k = _kind(e)
        d = by_kind.setdefault(k, {"kind": k, "label": _label(k), "count": 0, "high_critical": 0})
        d["count"] += 1
        d["high_critical"] += 1 if high(e) else 0
    by_kind_l = sorted(by_kind.values(), key=lambda d: (-d["high_critical"], -d["count"]))

    by_cam: dict[str, dict] = {}
    for e in evs:
        d = by_cam.setdefault(e.camera_name or e.camera_id, {"camera": e.camera_name or e.camera_id, "count": 0, "high_critical": 0})
        d["count"] += 1
        d["high_critical"] += 1 if high(e) else 0
    by_cam_l = sorted(by_cam.values(), key=lambda d: (-d["high_critical"], -d["count"]))

    zones = Counter(e.zone_name for e in evs if e.zone_name)
    sev = Counter(e.severity for e in evs)

    # hourly timeline across the whole period (capped at 168 buckets so a 30-day brief stays readable)
    bucket_h = 1 if hours <= 168 else 24
    n_buckets = min(168, max(1, hours // bucket_h))
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=bucket_h * (n_buckets - 1))
    buckets = [{"hour": _iso(start + timedelta(hours=bucket_h * i)), "count": 0, "high_critical": 0} for i in range(n_buckets)]
    for e in evs:
        idx = int((_utc(e.created_at) - start).total_seconds() // (3600 * bucket_h))
        if 0 <= idx < n_buckets:
            buckets[idx]["count"] += 1
            buckets[idx]["high_critical"] += 1 if high(e) else 0

    top = sorted(evs, key=lambda e: (-SEV_RANK.get(e.severity, 0), -_utc(e.created_at).timestamp()))[:10]
    top_l = [_incident_row(e) for e in top]

    evidence = sum(1 for e in evs if e.snapshot_path or e.clip_path)
    totals = {
        "events": len(evs), "high_critical": sum(1 for e in evs if high(e)), "critical": sev.get("critical", 0),
        "with_evidence": evidence, "cameras": len(by_cam), "false_positive": sum(1 for e in evs if e.status == "false_positive"),
    }

    # plain-language headline
    lines: list[str] = []
    if not evs:
        lines.append(f"No incidents were recorded in the last {hours} hour(s).")
    else:
        lines.append(f"{len(evs)} incident(s) in the last {hours} hour(s) across {len(by_cam)} camera(s); "
                     f"{totals['high_critical']} of them high or critical, {evidence} with a saved snapshot / clip.")
        worst = [d for d in by_kind_l if d["high_critical"]][:3]
        if worst:
            lines.append("Most serious: " + ", ".join(f"{d['label']} ({d['high_critical']})" for d in worst) + ".")
        busiest = max(buckets, key=lambda b: b["count"])
        if busiest["count"] > 0:
            lines.append(f"Busiest {'hour' if bucket_h == 1 else 'day'}: {busiest['hour'][11:16] if bucket_h == 1 else busiest['hour'][:10]} UTC with {busiest['count']} incident(s).")
        if zones:
            z, n = zones.most_common(1)[0]
            lines.append(f"Most active zone: {z} ({n}).")
        if totals["false_positive"]:
            lines.append(f"{totals['false_positive']} incident(s) were marked as false positives by reviewers.")

    return {"hours": hours, "from": _iso(since), "to": _iso(now), "totals": totals, "headline": lines, "by_kind": by_kind_l,
            "by_severity": {k: sev.get(k, 0) for k in ("critical", "high", "medium", "low", "info")}, "by_camera": by_cam_l,
            "by_zone": [{"zone": z, "count": n} for z, n in zones.most_common(8)], "by_hour": buckets, "bucket_hours": bucket_h,
            "top_incidents": top_l}
