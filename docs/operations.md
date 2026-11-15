# Operations

## Processes

| Service | Health | Notes |
|---|---|---|
| `db` | `pg_isready` | PostgreSQL 17. The application role `aurex_app` and row-level security policies are created by the migration job. |
| `migrate` | exits 0 | Runs migrations, security policies, the license register, the dataset catalog and the curated graph. Safe to re-run. |
| `api` | `GET /api/v1/health` | Returns 200 when the database answers. |
| `worker` | logs `worker.started` | Schedules imports every minute; answers questions; refreshes alerts, theses and the graph after imports. |
| `web` | `GET /` | Next.js standalone server. |
| `proxy` | ports 80/443 | Caddy with automatic certificates for `AUREX_DOMAIN` (production overlay). |

## First start

1. `cp .env.example .env`; set `AUREX_DB_PASSWORD`, `AUREX_SECRET_KEY` (`openssl rand -hex 32`),
   `AUREX_DOMAIN`, `ACME_EMAIL`, `AUREX_SEC_USER_AGENT`, and optional AI, email and billing settings.
2. `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile app up -d --build`
3. Open `https://<domain>/signup`. The first account becomes the platform administrator.
4. Set `AUREX_ALLOW_SIGNUP=false` if only invited users should get accounts.

## Backups and restore

```bash
pwsh ./scripts/Backup-AurexDatabase.ps1 -Destination ./backups -RetentionDays 14
```

```bash
pwsh ./scripts/Restore-AurexDatabase.ps1 -Path ./backups/<file>.dump
```

Schedule the backup daily (cron or a systemd timer) and copy `./backups` off the host. Run a restore
drill on staging in every release cycle; the scripts are tested with Pester in CI.

## Upgrades

Pull the new images (or check out the new tag), then run `docker compose ... up -d --build`. The
migration job runs first; the API and worker start only after it succeeds.

## Monitoring

- Logs are JSON on stdout. Alert on `"severity": "SECURITY"` and on `ingestion.failed`.
- DataLab shows each dataset's status; the status bar in the terminal shows how many need attention.
- `GET /api/v1/health` for uptime checks.

## Billing (cloud mode)

Create products and recurring prices in Stripe, set `AUREX_STRIPE_PRICES` (for example
`{"pro":"price_...","quant":"price_...","business":"price_..."}`), `AUREX_PLAN_PRICE_LABELS`, and add a
webhook endpoint `https://<domain>/api/v1/billing/webhook` for `checkout.session.completed` and
`customer.subscription.*` events. Put its signing secret in `AUREX_STRIPE_WEBHOOK_SECRET`. Enable the
customer portal in Stripe so owners can change plans and download invoices.
