"""Outbound email through the operator's SMTP server. Used for invitations only."""

import smtplib
import ssl
from email.message import EmailMessage

from core.config import get_settings
from modules.logging import Severity, log


def configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def send(*, to: str, subject: str, body: str) -> bool:
    """Send a plain-text message. Returns False when email is not configured or delivery failed."""
    settings = get_settings()
    if not configured():
        return False
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.smtp_from, to, subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_starttls:
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log("integration", "mail.failed", Severity.WARN, error=type(exc).__name__)
        return False
