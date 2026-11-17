# Logging and audit

## Log schema

One JSON object per line on stdout:

```json
{"timestamp": "2026-11-15T09:40:17.293+00:00", "module": "datalab", "event": "ingestion.completed",
 "severity": "INFO", "details": {"dataset": "demo", "stored": {"observations": 22550}}}
```

Severities: `INFO`, `WARN`, `ERROR`, `SECURITY`. Every API request is logged with route template, status,
duration, tenant and request id — never with query strings, bodies or headers.

## Sanitization

`modules.logging.sanitize` runs on every record and audit detail:

- keys that name credentials, personal data or content (`password`, `token`, `cookie`, `email`,
  `question`, `body`, `content`, `stack` and others) are replaced with `[redacted]`;
- values are scanned for email addresses, AUREX and payment keys, bearer tokens, JWTs, database URLs with
  passwords and card-like numbers;
- values are truncated and nesting is bounded.

`tests/test_core.py::test_log_schema_and_forbidden_data` is the forbidden-data gate.

## Audit trail

`audit_events` is append-only: the application role cannot update or delete it and a trigger rejects
both for every role. Recorded actions include sign-up, sign-in (success and denial), sign-out, password
changes, API keys, invitations, roles, member removal, watchlist, alert, portfolio and thesis changes,
exports, questions and every agent tool call, uploads, backtests, graph proposals and reviews, billing
plan changes and platform administration. Administrators on plans with the audit entitlement can read
their organization's trail in Settings → Audit trail.
