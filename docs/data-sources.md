# Data sources and licenses

Terms checked on 2026-11-10. The license register (`modules/datalab/catalog.py`, visible in DataLab →
License register) is the source of truth the system enforces.

| Dataset | Provider | Content | Freshness | License class | Uses permitted |
|---|---|---|---|---|---|
| `demo` | AUREX | Ten fictional companies, an index, generated prices, fundamentals and reports | demonstration | demonstration | all |
| `ecb-fx` | European Central Bank | Euro reference exchange rates (about 30 currencies) since 2010 | end of day | public | all, with attribution |
| `ecb-rates` | European Central Bank | Deposit, refinancing and marginal lending rates, €STR, AAA yields 2Y and 10Y | end of day | public | all, with attribution |
| `ecb-macro` | European Central Bank | Real GDP growth; HICP inflation (ICP dataset ends 2025-12) | historical | public | all, with attribution |
| `ecb-press` | European Central Bank | Titles and links of press releases, speeches and interviews | delayed | public | titles and links only |
| `sec-index` | U.S. SEC (EDGAR) | Companies with tickers | historical | public | all |
| `sec-companies` | U.S. SEC (EDGAR) | Filings (10-K, 10-Q, 8-K, 20-F) and XBRL facts for tracked companies | delayed | public | all |
| `uploads-*` | The customer | Documents uploaded by one organization | historical | tenant private | not sent to external models |

## Obligations

- **ECB:** cite the source; do not modify statistics; derived values are labeled as AUREX calculations.
  Third-party data inside ECB datasets is excluded from reuse.
- **SEC:** at most 10 requests per second (the connector paces at 4); automated clients send a
  User-Agent naming the operator and a contact (`AUREX_SEC_USER_AGENT`). Without it the SEC datasets
  stay "not configured" and make no requests.
- **Commercial price data** (for example Financial Modeling Prep) requires a display and redistribution
  agreement before more than one person sees it. Add such a dataset with its own license record, a
  `licensed` data class, and the delay and channel flags from the contract; only Enterprise tenants hold
  the `data.licensed` entitlement.

## Publication times

Point-in-time reads use `known_at`. Where the provider states no publication time a conservative estimate
is used: daily ECB series +36 hours, monthly +35 days, quarterly +50 days. ECB reference rates are known
at 15:00 UTC on their day. Revisions are stored as new versions with the time they were seen.
