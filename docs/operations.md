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
3. Open `https://<domain>/signup` and create the account whose email is in `AUREX_PLATFORM_ADMIN_EMAILS`;
   it becomes the platform administrator and may sign up even while sign-up is closed. Production has no
   other way to get an administrator; outside production, without that setting, the first account does.
4. Set `AUREX_ALLOW_SIGNUP=false` if only invited users should get accounts.

## Behind an existing reverse proxy

On a host where another proxy already owns ports 80 and 443, use `deploy/docker-compose.edge.yml`
instead of the production overlay. It publishes nothing, and it needs no secrets from you: on first
start the `init-secrets` job generates the database password and `AUREX_SECRET_KEY` into the
`app-secrets` volume, readable only by the database and the application, and never replaces them.
Back that volume up together with the database. More secrets can be added to it as files named after
the variable (`aurex_anthropic_api_key`, `aurex_stripe_secret_key`, ...) or set in `.env`.

Site settings go in `.env` or in one more override file kept out of git, for example `compose.site.yml`:

```yaml
x-site: &site
  AUREX_PUBLIC_URL: https://aurex.example.com
  AUREX_PLATFORM_ADMIN_EMAILS: '["ops@example.com"]'
  AUREX_CLIENT_IP_HEADER: CF-Connecting-IP
  AUREX_SEC_USER_AGENT: Example Ltd ops@example.com
services:
  migrate: { environment: *site }
  api: { environment: *site }
  worker: { environment: *site }
```

```bash
docker compose -p aurex -f docker-compose.yml -f deploy/docker-compose.edge.yml -f compose.site.yml --profile app up -d --build
```

The edge proxy joins the `aurex_default` network and routes the hostname:

```
aurex.example.com {
	encode zstd gzip
	request_body {
		max_size 10MB
	}
	@api path /api/*
	reverse_proxy @api aurex-api-1:8000
	reverse_proxy aurex-web-1:3000
}
```

Route with matchers on `reverse_proxy` as above rather than `handle` blocks: Caddy runs `handle` before
`respond`, so access rules written with `respond` (an origin lock such as "403 unless the request comes
from Cloudflare") would never apply.

Set `AUREX_CLIENT_IP_HEADER` to the header your proxy or CDN uses for the visitor's address (for
example `CF-Connecting-IP` behind Cloudflare) so sign-in limits apply per visitor, and only when the
origin accepts traffic from that proxy alone.

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

On a Stripe account shared with other products, every product's webhook receives every event. AUREX
marks its customers, checkouts and subscriptions with the metadata `app: aurex`, acts only on checkouts
that carry it, and ignores subscriptions of customers it does not know. Create a portal configuration for
AUREX (its own headline, legal links, return URL and the AUREX prices customers may switch between) and
set its id in `AUREX_STRIPE_PORTAL_CONFIGURATION`; otherwise the account's default portal is shown.

To collect sales tax or VAT with Stripe Tax, first complete its settings in the Stripe Dashboard (head
office address and a registration for every place you are registered), give the AUREX products a tax
code and the prices a tax behavior, then set `AUREX_STRIPE_AUTOMATIC_TAX=true`. Checkout then requires a
billing address, saves it on the customer, accepts business tax ids and adds the tax.
