# AUREX

A financial research terminal for analysis, education and simulation. Market data, filings, portfolio
risk, backtests and a market impact graph in one environment, where every number shows its source, age
and license, and every AI statement links to the evidence behind it.

AUREX does not execute trades and does not give investment advice.

## What is in the box

| Module | What it does |
|---|---|
| Markets | Instrument search, charts with indicators, watchlists with pinning, price alerts, screener, correlations, event calendar, configurable workspaces |
| Intelligence | Questions answered by six agents (Research, Earnings, Macro, Risk, Data Quality, Thesis Monitor) with cited evidence, claim verification, reproducible answer records, document search and upload, company fundamentals, thesis monitoring |
| Portfolio | Virtual portfolios, CSV import, time-weighted returns, benchmark comparison, exposures, concentration, limits, stress scenarios |
| Quant | Point-in-time backtests with mandatory costs and latency, in- and out-of-sample reporting, variant counting, seeded Monte Carlo simulation |
| Graph | Market Impact Graph: typed links with source, method and confidence, scenario paths, link proposals and review |
| DataLab | Dataset catalog with freshness, run history and quality flags; license register enforced at ingestion, retrieval, AI context and output |

Platform: organizations with roles, invitations, API keys, append-only audit trail, plans as entitlement
sets, Stripe subscriptions in cloud mode, row-level security on every tenant table.

Data shipped with the build: ECB exchange rates, key interest rates, yields and macro indicators; ECB
press feed; SEC EDGAR filings and reported facts (with an operator-supplied contact); a fictional
demonstration market for trying every module without a data contract.

## Quick start (local)

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22.

```bash
docker compose up -d db
uv sync
uv run python -m pipelines.bootstrap
uv run python -m scripts.seed_dev
```

Then run the three processes, each in its own terminal:

```bash
uv run uvicorn interface.api.main:app --port 8000
```

```bash
uv run python -m pipelines.worker
```

```bash
npm --prefix interface/terminal-web install && npm --prefix interface/terminal-web run dev
```

Open http://localhost:3000 and sign in with the development account printed by `scripts.seed_dev`, or
create a workspace. The worker imports the demonstration market and the ECB datasets within a minute.

## Run the whole stack in containers

```bash
cp .env.example .env   # set AUREX_DB_PASSWORD and AUREX_SECRET_KEY at least
docker compose --profile app up -d --build
```

The web terminal is served on http://127.0.0.1:3000 and the API on http://127.0.0.1:8000.

## Production

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile app up -d --build
```

The overlay puts Caddy in front with automatic TLS for `AUREX_DOMAIN`, publishes nothing else, and turns
on secure cookies. See [docs/operations.md](docs/operations.md) for configuration, backups, upgrades and
monitoring, and [docs/deployment-checklist.md](docs/deployment-checklist.md) before going live.

## Configuration

All settings are environment variables prefixed `AUREX_`; [.env.example](.env.example) lists them with
explanations. The important ones:

| Variable | Purpose |
|---|---|
| `AUREX_DEPLOYMENT_MODE` | `local`, `self_hosted` or `cloud`. Cloud starts new organizations on Community and enables billing. |
| `AUREX_SECRET_KEY` | Required in production. |
| `AUREX_ANTHROPIC_API_KEY` | Enables the model-driven AI engine. Without it, the offline evidence engine answers. |
| `AUREX_SEC_USER_AGENT` | Name and contact address, required by the SEC for EDGAR access. |
| `AUREX_STRIPE_*` | Secret key, webhook secret and plan price ids for subscriptions. |
| `AUREX_SMTP_*` | Email for invitations. Without it, administrators copy the invitation link. |

## Development

```bash
uv run pytest                      # 126 tests: unit, integration, isolation, license, AI evaluation
uv run ruff check . && uv run lint-imports
npm --prefix interface/terminal-web test
npm --prefix interface/terminal-web run lint
```

Tests create their own database (`aurex_test`) and never call external services.

## Documentation

- [Architecture](docs/architecture.md), [modules](docs/modules.md), [data flow](docs/data-flow.md)
- [Security and threat model](docs/security.md), [validation](docs/validation.md), [logging and audit](docs/logging.md)
- [Data sources and licenses](docs/data-sources.md), [AI evaluation](docs/ai-evaluation.md)
- [CI/CD](docs/ci-cd.md), [operations](docs/operations.md), [deployment checklist](docs/deployment-checklist.md)
- [Architecture decision records](docs/adr/)
- [Project definition](docs/aurex-project-definition.md)
- API reference: `/api/v1/docs` on a running deployment

## License

Proprietary. Third-party components keep their own licenses; the chart library (TradingView Lightweight
Charts, Apache-2.0) requires the attribution shown on every chart.
