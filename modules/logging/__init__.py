"""Structured logging and the audit trail.

Log schema: ``timestamp, module, event, severity, details``. Severities: INFO, WARN, ERROR, SECURITY.
Details are sanitized before they are written: credentials, tokens, personal data and raw payloads
never reach a log line. Only this module writes logs and audit events.
"""

from modules.logging.audit import AuditEvent, record_audit
from modules.logging.log import Severity, log, sanitize

__all__ = ["AuditEvent", "Severity", "log", "record_audit", "sanitize"]
