# Security

## Controls by threat (threat model v1)

| ID | Threat | Controls in this build | Tests |
|---|---|---|---|
| T-01 | Malformed provider data | Schema validation per connector; atomic batches; previous version kept; quality flags | `tests/test_ingestion.py` |
| T-02 | Injection through requests | Pydantic schemas with unknown fields rejected; parameterized SQL; CSV formula cells rejected | `tests/test_core.py`, `tests/test_api_markets.py` |
| T-03 | Prompt injection in documents | Passages screened at ingestion and again at use; flagged text never reaches a model; agents read-only; side effects need confirmation | `tests/test_intelligence.py`, `tests/eval` |
| T-04 | Data leaving through agents | Agents act with the user's scope; license channel `model_external` vs `model_local`; tenant policy can deny external models; only `integration` makes outbound calls | `test_external_model_policy_excludes_data_not_cleared_for_it` |
| T-05 | Cross-tenant access | Application filters plus row-level security under an unprivileged role; tests for reads and writes | `tests/test_isolation.py` |
| T-06 | License breach | License register checked per channel (display, api, export, model) | `test_export_is_blocked_by_the_license_register`, `test_api_keys_use_the_api_channel` |
| T-07 | Arbitrary user code | Not executed. Strategies and indicators are declarative and evaluated by the engine (ADR-0009). | `tests/test_quant.py` |
| T-08 | SSRF via connectors | Host allow-list; https only; private, loopback and link-local addresses refused; no redirects | `test_outbound_calls_are_limited_to_the_allow_list` |
| T-09 | Secrets or personal data in logs | Key-based and pattern-based sanitization of every log record and audit detail | `test_log_schema_and_forbidden_data` |
| T-10 | Wrong financial results | Reference-value tests; versioned engine; Decimal money with explicit currency | `tests/test_processing.py`, `tests/test_portfolio.py` |
| T-11 | Cost exhaustion | Per-tenant rate limit; daily AI quota per plan; step, time and tool-call budgets per agent run; backtests per day | `test_daily_question_quota`, `test_budgets_stop_the_loop` |
| T-12 | Compromised dependency | Locked dependencies; `pip-audit` and `npm audit` in CI; secret scanning | CI `audit` job |
| T-13 | Privilege escalation | Role checks at every mutating endpoint; last owner protected; platform admin separate | `tests/test_org_billing.py` |
| T-15 | Audit tampering | `audit_events` revoked for update and delete from the app role, and a trigger rejects both for every role | `test_audit_trail_is_append_only_and_tenant_scoped` |
| T-16 | Misleading output | Claim verifier; inference labeled; gaps listed; scenarios and simulations labeled as not forecasts | `tests/test_intelligence.py`, `tests/test_graph.py` |

T-14 (stream subscriptions) does not apply yet: the build has no WebSocket endpoints.

## Authentication and sessions

- Passwords: Argon2id; strength rules; constant-time comparison including for unknown accounts.
- Browser sessions: random 256-bit tokens, stored as SHA-256 hashes; `HttpOnly`, `SameSite=Lax`,
  `Secure` in production. State-changing requests from a cookie session must carry the
  `X-Aurex-Client` header, which a cross-site form cannot set.
- API keys: `aurex_` prefix, hashed at rest, shown once, revocable, limited to plans with API access, and
  reads through them use the `api` license channel.
- Rate limits on sign-in by address and by account, on sign-up and on invitation acceptance.

## Headers

API: `X-Content-Type-Options`, `Referrer-Policy`, `Cache-Control: no-store`, request id. Web (production):
Content-Security-Policy, HSTS, `X-Frame-Options: DENY`, Permissions-Policy.

## Known limits and next steps

- The rate limiter is per process. With several API processes, add a limit at the proxy.
- Content screening is pattern-based; a model-based classifier would catch paraphrased instructions.
- Uploads accept plain text and Markdown only; PDF parsing would need a sandboxed parser.
- Penetration testing by a third party is required before a public launch (docs/deployment-checklist.md).
