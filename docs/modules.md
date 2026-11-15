# Modules

Each entry lists responsibilities, interface, boundaries and security controls. Code paths are relative to
the repository root.

## Platform modules

| Module | Path | Responsibilities | Must not |
|---|---|---|---|
| core | `core/` | Settings, canonical interface objects, errors, money, database primitives, row-level security setup | Contain business logic or call external systems |
| validation | `modules/validation` | Strict and lenient schemas, text cleaning, symbol checks, untrusted CSV parsing | Repair data |
| logging | `modules/logging` | Structured JSON logs with sanitization; append-only audit events | Record credentials, personal data or document text |
| integration | `modules/integration` | ECB, SEC and demonstration connectors; HTTP with allow-list and SSRF guard; Anthropic model adapter; Stripe; SMTP | Pass unvalidated responses onward |
| processing | `modules/processing` | Series statistics, indicators, fundamentals and ratios, portfolio accounting and TWR, scenarios, backtests, Monte Carlo | Read or write storage; return a figure without its inputs |
| analysis | `modules/analysis` | Tool registry, budgets, model loop, evidence ledger, claim verifier | Call external systems directly; originate figures |

## Product modules

### Markets (`modules/markets`)
Charts with interval, range and indicator overlays; watchlists with pinning and sharing; alert rules and
notifications; screener; correlations; calendar; saved workspaces. Every chart carries provenance.

### Intelligence (`modules/intelligence`)
Questions are stored as answer records and run by the worker. Six agents with allow-listed tools; the
offline evidence engine or the model engine writes; the verifier checks every statement. Also document
search and upload (screened), company fundamentals, and theses monitored after each import.

### Portfolio (`modules/portfolio`)
Virtual portfolios and transactions (manual or CSV), average-cost accounting, valuation in a base currency
with ECB rates, time-weighted return, benchmark, exposures, concentration, limits, scenarios.

### Quant (`modules/quant`)
Declarative strategies (buy and hold, moving-average crossover, momentum, RSI reversion) backtested on
point-in-time data with explicit costs and latency; variants counted per strategy and instrument; seeded
Monte Carlo on instruments or portfolios. Runs are stored with their data cut-off for reproduction.

### Graph (`modules/graph`)
Nodes and typed links with source, method, confidence and review status; curated macro transmission links;
company exposures taken from filings with the passage as evidence; statistical co-movement estimates with
window and standard error; scenario paths with weakest-link confidence; proposals and review.

### DataLab (`modules/datalab`)
License register, dataset catalog, ingestion runs with quality summaries, the canonical store with
versioned observations and facts, and the access interface that enforces licenses per channel.
