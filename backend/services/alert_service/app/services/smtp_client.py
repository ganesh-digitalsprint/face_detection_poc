from __future__ import annotations

import smtplib
import socket
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import parseaddr


class SmtpDeliveryError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def validate_address(value: str) -> str:
    candidate = value.strip()
    if not candidate or "\r" in candidate or "\n" in candidate:
        raise SmtpDeliveryError("invalid_recipient", "A configured recipient address is invalid")
    display, parsed = parseaddr(candidate)
    if display or parsed != candidate or "@" not in parsed or parsed.startswith("@") or parsed.endswith("@"):
        raise SmtpDeliveryError("invalid_recipient", "A configured recipient address is invalid")
    return parsed


def send_email(settings, *, recipients: list[str], subject: str, body: str, html_body: str | None = None,
               inline_images: list[dict] | None = None, smtp_factory=smtplib.SMTP) -> None:
    if not settings.smtp_enabled:
        raise SmtpDeliveryError("disabled", "Email delivery is disabled")
    if not all((settings.smtp_host, settings.smtp_port, settings.smtp_username,
                settings.smtp_password, settings.smtp_from_email)):
        raise SmtpDeliveryError("not_configured", "Email delivery is not fully configured")
    if not recipients:
        raise SmtpDeliveryError("missing_recipient", "No email recipient is configured for this branch")

    safe_recipients = [validate_address(value) for value in recipients]
    from_email = validate_address(settings.smtp_from_email)
    if "\r" in subject or "\n" in subject:
        raise SmtpDeliveryError("invalid_message", "Email subject is invalid")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Address(display_name=settings.smtp_from_name, addr_spec=from_email)
    message["To"] = ", ".join(safe_recipients)
    message.set_content(body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
        html_part = message.get_body(preferencelist=("html",))
        for item in inline_images or []:
            html_part.add_related(item["data"], maintype=item["maintype"], subtype=item["subtype"],
                                  cid=f"<{item['cid']}>", filename=item["filename"], disposition="inline")

    try:
        with smtp_factory(settings.smtp_host, settings.smtp_port,
                          timeout=settings.smtp_timeout_seconds) as client:
            client.ehlo()
            if settings.smtp_use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(settings.smtp_username, settings.smtp_password)
            refused = client.send_message(message, from_addr=from_email, to_addrs=safe_recipients)
            if refused:
                raise SmtpDeliveryError("recipient_rejected", "The SMTP provider rejected a configured recipient")
    except SmtpDeliveryError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        raise SmtpDeliveryError("authentication_failed", "Gmail rejected the configured SMTP credentials") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise SmtpDeliveryError("recipient_rejected", "The SMTP provider rejected the configured recipients") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise SmtpDeliveryError("timeout", "The SMTP connection timed out") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise SmtpDeliveryError("connection_failed", "The SMTP provider could not accept the test email") from exc
