from __future__ import annotations

import smtplib
import socket
from types import SimpleNamespace

import pytest

from app.services.smtp_client import SmtpDeliveryError, send_email


def config(**changes):
    values = dict(smtp_enabled=True, smtp_host="smtp.gmail.com", smtp_port=587,
                  smtp_username="sender@example.invalid", smtp_password="fake-app-password",
                  smtp_from_email="sender@example.invalid", smtp_from_name="Fedbank Security Alerts",
                  smtp_use_tls=True, smtp_timeout_seconds=15)
    values.update(changes)
    return SimpleNamespace(**values)


class FakeSmtp:
    def __init__(self, host, port, timeout):
        self.connection = (host, port, timeout)
        self.calls = []
        self.message = None

    def __enter__(self): return self
    def __exit__(self, *_): self.calls.append("close")
    def ehlo(self): self.calls.append("ehlo")
    def starttls(self, *, context): self.calls.append(("starttls", context.check_hostname, context.verify_mode))
    def login(self, username, password): self.calls.append(("login", username, password))
    def send_message(self, message, *, from_addr, to_addrs):
        self.message = message
        self.calls.append(("send", from_addr, tuple(to_addrs)))
        return {}


def test_smtp_success_uses_starttls_authentication_and_acceptance():
    created = []
    def factory(*args, **kwargs):
        client = FakeSmtp(*args, **kwargs); created.append(client); return client

    send_email(config(), recipients=["recipient@example.invalid"], subject="Test", body="Plain text",
               smtp_factory=factory)

    client = created[0]
    assert client.connection == ("smtp.gmail.com", 587, 15)
    assert client.calls[0] == "ehlo"
    assert client.calls[1][0] == "starttls" and client.calls[1][1:] == (True, 2)
    assert client.calls[2] == "ehlo"
    assert client.calls[3] == ("login", "sender@example.invalid", "fake-app-password")
    assert client.calls[4] == ("send", "sender@example.invalid", ("recipient@example.invalid",))
    assert client.calls[5] == "close"
    assert client.message.get_content().strip() == "Plain text"


def test_smtp_adds_html_and_inline_snapshot_as_cid():
    client = FakeSmtp("smtp.gmail.com", 587, 15)
    send_email(config(), recipients=["recipient@example.invalid"], subject="Alert", body="Plain",
        html_body='<img src="cid:snapshot-1">',
        inline_images=[{"cid": "snapshot-1", "data": b"image", "maintype": "image",
                        "subtype": "jpeg", "filename": "snapshot.jpg"}],
        smtp_factory=lambda *_args, **_kwargs: client)
    html_part = next(part for part in client.message.walk() if part.get_content_type() == "text/html")
    image_part = next(part for part in client.message.walk() if part.get_content_maintype() == "image")
    assert "cid:snapshot-1" in html_part.get_content()
    assert image_part["Content-ID"] == "<snapshot-1>"
    assert image_part.get_content_disposition() == "inline"


@pytest.mark.parametrize(("settings", "recipients", "category"), [
    (config(smtp_enabled=False), ["recipient@example.invalid"], "disabled"),
    (config(smtp_password=""), ["recipient@example.invalid"], "not_configured"),
    (config(), [], "missing_recipient"),
    (config(), ["victim@example.invalid\r\nBcc: attacker@example.invalid"], "invalid_recipient"),
])
def test_smtp_rejects_unsafe_or_incomplete_configuration_without_connecting(settings, recipients, category):
    with pytest.raises(SmtpDeliveryError, match=".") as raised:
        send_email(settings, recipients=recipients, subject="Test", body="Body",
                   smtp_factory=lambda *_args, **_kwargs: pytest.fail("SMTP connection attempted"))
    assert raised.value.category == category


def test_smtp_maps_gmail_authentication_failure_safely():
    class AuthFailure(FakeSmtp):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"provider detail must remain private")
    with pytest.raises(SmtpDeliveryError) as raised:
        send_email(config(), recipients=["recipient@example.invalid"], subject="Test", body="Body",
                   smtp_factory=AuthFailure)
    assert raised.value.category == "authentication_failed"
    assert "provider detail" not in str(raised.value)


def test_smtp_maps_connection_timeout_without_connecting_again():
    def timeout(*_args, **_kwargs): raise socket.timeout("private network detail")
    with pytest.raises(SmtpDeliveryError) as raised:
        send_email(config(), recipients=["recipient@example.invalid"], subject="Test", body="Body",
                   smtp_factory=timeout)
    assert raised.value.category == "timeout"
    assert "private network detail" not in str(raised.value)


def test_smtp_maps_recipient_rejection_and_connection_failure_safely():
    class Refused(FakeSmtp):
        def send_message(self, message, *, from_addr, to_addrs):
            return {to_addrs[0]: (550, b"private provider detail")}
    with pytest.raises(SmtpDeliveryError) as rejected:
        send_email(config(), recipients=["recipient@example.invalid"], subject="Test", body="Body",
                   smtp_factory=Refused)
    assert rejected.value.category == "recipient_rejected"
    assert "provider detail" not in str(rejected.value)

    def unavailable(*_args, **_kwargs): raise OSError("private socket detail")
    with pytest.raises(SmtpDeliveryError) as failed:
        send_email(config(), recipients=["recipient@example.invalid"], subject="Test", body="Body",
                   smtp_factory=unavailable)
    assert failed.value.category == "connection_failed"
    assert "private socket detail" not in str(failed.value)
