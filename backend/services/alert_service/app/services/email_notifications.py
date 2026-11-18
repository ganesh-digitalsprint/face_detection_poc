from __future__ import annotations

import html
import logging
from datetime import timezone
from urllib.parse import quote, urlsplit

import httpx
from starlette.concurrency import run_in_threadpool

from app.db.models import Alert, BranchNotificationSettings, NotificationOutbox
from app.db.repositories import due_notifications, mark_delivery
from app.services.smtp_client import SmtpDeliveryError

logger = logging.getLogger(__name__)
def valid_public_url(value: str) -> bool:
    parsed = urlsplit(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


def _text(value, fallback="—"):
    if value is None or value == "":
        return fallback
    return str(value)


def render_alert_email(alert: Alert, *, public_base_url: str, branch_id: str,
                       snapshot_cid: str | None = None,
                       include_video_evidence: bool = False) -> tuple[str, str, str]:
    refs = alert.resource_refs or {}
    domain = alert.domain_data or {}
    branch = _text(refs.get("branch_name"), branch_id)
    title = _text(alert.title)
    severity = _text(alert.severity).upper()
    occurred = alert.occurred_at
    if occurred and occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    time_text = occurred.astimezone().strftime("%b %d, %Y, %I:%M %p %Z").replace(", 0", ", ") if occurred else "—"
    subject = f"[Fedbank] {severity}: {title} — {branch}"
    details = [
        ("Camera name", refs.get("camera_name")),
        ("Camera ID", refs.get("camera_id") or refs.get("registry_camera_id")),
        ("Branch", refs.get("branch_name") or branch_id),
        ("Branch code", refs.get("branch_code")),
        ("Place", refs.get("place") or refs.get("place_name")),
        ("Region", refs.get("region") or refs.get("region_name")),
        ("Branch manager", refs.get("branch_manager")),
        ("Use case", alert.use_case.replace("_", " ").title()),
        ("Detected time", time_text),
        ("Confidence", domain.get("confidence")),
        ("Covering type", domain.get("covering_type")),
        ("Track ID", domain.get("track_id") if domain.get("track_id") is not None
         else ", ".join(str(value) for value in domain.get("track_ids", [])[:10])),
        ("Video time", domain.get("video_timestamp_seconds")),
    ]
    details = [(label, f"{value:g} s" if label == "Video time" and isinstance(value, (int, float)) else _text(value))
               for label, value in details if value is not None and value != ""]
    link = f"{public_base_url.rstrip('/')}/alerts?alert_id={quote(alert.id)}"
    has_video = include_video_evidence and any(
        str(item.get("type", "")).lower() in {"clip", "video"} for item in (alert.evidence_refs or [])
        if isinstance(item, dict))
    image_html = (f'<img alt="Alert snapshot" src="cid:{html.escape(snapshot_cid)}" '
                  'style="display:block;max-width:100%;height:auto;border-radius:8px">') if snapshot_cid else "<p>Snapshot unavailable</p>"
    rows = "".join(f'<tr><td style="padding:8px;color:#52627e;border-bottom:1px solid #e4e8f0">{html.escape(label)}</td>'
                   f'<td style="padding:8px;text-align:right;font-weight:600;border-bottom:1px solid #e4e8f0">{html.escape(value)}</td></tr>'
                   for label, value in details)
    safe = lambda value: html.escape(_text(value))
    body = (f"{severity}: {title}\n{_text(alert.summary)}\nBranch: {branch}\nDetected: {time_text}\n"
            f"Alert details: {', '.join(f'{k}: {v}' for k,v in details)}\nOpen alert: {link}")
    document = f'''<!doctype html><html><body style="margin:0;background:#f3f5fa;font-family:Arial,sans-serif;color:#14213d">
<div style="max-width:560px;margin:0 auto;padding:18px"><div style="font-weight:bold;color:#3728a8">Fedbank <span style="font-weight:normal;color:#65718b">Security monitoring</span></div>
<main style="margin-top:12px;background:#fff;border:1px solid #dce2ee;border-radius:14px;padding:20px">
<p><span style="background:#fff0c2;color:#a85b00;padding:5px 9px;border-radius:20px">{safe(severity)}</span> <span style="color:#53627d">{safe(alert.id)}</span></p>
<h2 style="font-size:20px;margin:10px 0">{safe(title)}</h2><p style="color:#52627e">Detected {safe(time_text)} · {safe(branch)} · {safe(refs.get('camera_name'))}</p>
<p>{safe(alert.summary)}</p><h3>Evidence</h3><div style="background:#e5e8ee;padding:10px;border-radius:10px">{image_html}</div>
<p style="font-size:12px;color:#667590">Snapshot captured at {safe(time_text)}</p><h3>Alert details</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
{f'<p><a href="{html.escape(link, quote=True)}">View video evidence in Fedbank</a></p>' if has_video else ''}
<p style="text-align:center;margin:24px"><a href="{html.escape(link, quote=True)}" style="background:#3228a6;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">View alert in Fedbank</a></p>
<p style="text-align:center;color:#75819b;font-size:12px">Acknowledge, resolve or dismiss this alert from the alert page.</p></main></div></body></html>'''
    return subject, body, document


async def _snapshot(alert: Alert, branch_id: str, config):
    """Resolve a captured image through its owning service and return embedded bytes."""
    if not alert.source_event_id:
        return None
    if alert.use_case == "branch_exterior":
        return await _branch_snapshot(alert, branch_id, config.branch_exterior_base_url)
    if alert.use_case == "vault_monitoring":
        return await _vault_snapshot(alert, config)
    return None


async def _branch_snapshot(alert: Alert, branch_id: str, base_url: str,
                           *, client_factory=httpx.AsyncClient):
    # Fetch a Branch Exterior event by exact source ID and verify its branch.
    if not valid_public_url(base_url):
        return None
    base_url = base_url.rstrip("/")
    try:
        async with client_factory(timeout=httpx.Timeout(4.0), follow_redirects=False) as client:
            response = await client.get(f"{base_url}/api/events/{quote(alert.source_event_id, safe='')}")
            if response.status_code != 200:
                return None
            event = response.json()
            if str(event.get("id")) != alert.source_event_id:
                return None
            meta = event.get("meta") or {}
            if str(meta.get("branch_id")) != branch_id:
                return None
            relative = event.get("snapshot_path")
            if not isinstance(relative, str) or "\\" in relative:
                return None
            parts = relative.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                return None
            if not parts or parts[0] not in {"snapshots", "screenshots", "evidence"}:
                return None
            suffix = parts[-1].lower().rsplit(".", 1)[-1] if "." in parts[-1] else ""
            if suffix not in {"jpg", "jpeg", "png"}:
                return None
            file_response = await client.get(f"{base_url}/api/storage/file/{quote(relative, safe='/')}")
            return _image_attachment(file_response, max_bytes=5_000_000)
    except Exception as exc:
        logger.info("Alert snapshot unavailable (%s)", type(exc).__name__)
        return None


async def _vault_snapshot(alert: Alert, config, *, client_factory=httpx.AsyncClient):
    """Use the same Vault alert/evidence access APIs as Alert Center, then fetch bytes server-side."""
    base_url = str(getattr(config, "vault_evidence_api_url", "") or "").rstrip("/")
    api_key = str(getattr(config, "vault_evidence_api_key", "") or "")
    if not api_key or not valid_public_url(base_url):
        return None
    headers = {"X-API-Key": api_key}
    source_id = alert.source_event_id
    try:
        async with client_factory(timeout=httpx.Timeout(5.0), follow_redirects=False) as client:
            source_response = await client.get(
                f"{base_url}/api/v1/alerts/{quote(source_id, safe='')}", headers=headers)
            if source_response.status_code != 200:
                return None
            source = source_response.json()
            if str(source.get("id")) != source_id:
                return None
            refs = source.get("evidence_refs") if isinstance(source.get("evidence_refs"), list) else []
            if source.get("evidence_count") == 0:
                refs = []
            primary_id = source.get("primary_evidence_id")
            if primary_id and not any(str(ref.get("id")) == str(primary_id) for ref in refs if isinstance(ref, dict)):
                refs = [*refs, {"provider": "vault_monitoring", "id": primary_id, "type": "snapshot"}]
            snapshot_refs = [ref for ref in refs if isinstance(ref, dict)
                and ref.get("provider") == "vault_monitoring" and ref.get("type") == "snapshot"
                and ref.get("id")]
            selected = next((ref for ref in snapshot_refs if str(ref["id"]) == str(primary_id)),
                            snapshot_refs[0] if snapshot_refs else None)
            if selected is None:
                return None
            evidence_id = str(selected["id"])

            metadata_response = await client.get(
                f"{base_url}/api/v1/evidence/{quote(evidence_id, safe='')}", headers=headers)
            if metadata_response.status_code != 200:
                return None
            metadata = metadata_response.json()
            if (str(metadata.get("id")) != evidence_id
                    or str(metadata.get("alert_id")) != source_id
                    or metadata.get("available") is not True
                    or not str(metadata.get("mime_type") or "").lower().startswith("image/")):
                return None

            access_response = await client.post(f"{base_url}/api/v1/evidence/access",
                headers=headers, json={"ids": [evidence_id], "variant": "full"})
            if access_response.status_code != 200:
                return None
            item = next((candidate for candidate in access_response.json().get("items", [])
                         if str(candidate.get("id")) == evidence_id and not candidate.get("error")), None)
            if item is None:
                return None

            retrieval_path = item.get("retrieval_path")
            if retrieval_path:
                variant = item.get("variant_used", "full")
                if variant not in {"thumb", "full"}:
                    return None
                expected_path = f"/api/v1/evidence/{quote(evidence_id, safe='')}/content?variant={variant}"
                if retrieval_path != expected_path:
                    return None
                image_response = await client.get(f"{base_url}{expected_path}", headers=headers)
            else:
                # Cloudinary access URLs are generated by Vault for this exact
                # verified evidence ID; they are fetched here, never placed in HTML.
                signed_url = item.get("url")
                parsed = urlsplit(signed_url or "")
                if (parsed.scheme != "https" or parsed.hostname != "res.cloudinary.com"
                        or parsed.username or parsed.password):
                    return None
                image_response = await client.get(signed_url, follow_redirects=False)
            return _image_attachment(image_response, max_bytes=10_000_000)
    except Exception as exc:
        logger.info("Vault alert snapshot unavailable (%s)", type(exc).__name__)
        return None


def _image_attachment(response, *, max_bytes: int):
    if response.status_code != 200 or len(response.content) > max_bytes:
        return None
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if mime not in {"image/jpeg", "image/png"}:
        return None
    subtype = "jpeg" if mime == "image/jpeg" else "png"
    return {"cid": "alert-snapshot", "data": response.content, "maintype": "image",
            "subtype": subtype, "filename": f"snapshot.{subtype}"}


async def dispatch_email_once(session_factory, config, *, sender=None, max_attempts=8) -> int:
    sender = sender or _send_email
    with session_factory() as db:
        rows = due_notifications(db, channel="email")
        jobs = []
        for row in rows:
            alert = db.get(Alert, row.alert_id)
            saved = db.get(BranchNotificationSettings, row.branch_id) if row.branch_id else None
            jobs.append((row.id, row.alert_id, row.branch_id, row.recipient, alert, saved))
    attempted = 0
    for delivery_id, alert_id, branch_id, recipient, alert, saved in jobs:
        with session_factory() as db:
            row = db.get(NotificationOutbox, delivery_id)
            if not row or row.status != "SENDING":
                continue
            if (not alert or not saved or not saved.email_enabled or not recipient
                    or recipient.lower() not in {x.lower() for x in (saved.to_recipients or [])}
                    or alert.severity.lower() not in (saved.severity_filters or [])
                    or alert.use_case.lower() not in (saved.use_case_filters or [])):
                row.status = "CANCELLED"
                row.last_error = "settings_changed"
                db.commit()
                continue
        if not config.email_notifications_enabled or not valid_public_url(config.public_app_base_url):
            success, retryable, error, provider_id = False, False, "email_delivery_not_configured", None
            snapshot = None
        else:
            snapshot = await _snapshot(alert, branch_id, config) if saved.include_snapshot else None
            subject, body, html_body = render_alert_email(alert, public_base_url=config.public_app_base_url,
                branch_id=branch_id, snapshot_cid=snapshot["cid"] if snapshot else None,
                include_video_evidence=bool(saved.include_video_evidence))
            try:
                provider_id = await run_in_threadpool(sender, config, recipients=[recipient], subject=subject,
                    body=body, html_body=html_body, inline_images=[snapshot] if snapshot else [])
                success, retryable, error = True, True, None
            except SmtpDeliveryError as exc:
                provider_id, error = None, exc.category
                retryable = exc.category in {"timeout", "connection_failed"}
                success = False
            except Exception as exc:
                logger.warning("Alert email delivery failed (%s)", type(exc).__name__)
                provider_id, error, retryable, success = None, type(exc).__name__[:100], True, False
        with session_factory() as db:
            row = db.get(NotificationOutbox, delivery_id)
            if row and row.status == "SENDING":
                mark_delivery(db, row, success=success, error=error, provider_id=provider_id,
                    max_attempts=max_attempts, retryable=retryable, success_status="ACCEPTED")
        attempted += 1
    return attempted


def _send_email(config, *, recipients, subject, body, html_body, inline_images):
    from app.services.smtp_client import send_email
    return send_email(config, recipients=recipients, subject=subject, body=body,
                      html_body=html_body, inline_images=inline_images)
