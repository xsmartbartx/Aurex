# Deployment checklist

## Before the first production deployment

- [ ] `.env` filled from `.env.example`; `AUREX_ENVIRONMENT=production`; strong `AUREX_SECRET_KEY` and database password
      (behind a shared proxy, `deploy/docker-compose.edge.yml` generates both; back up its `app-secrets` volume).
- [ ] `AUREX_PUBLIC_URL` is the site's `https://` address (production refuses to start otherwise).
- [ ] DNS for `AUREX_DOMAIN` points at the host; ports 80 and 443 open; nothing else published.
- [ ] `AUREX_SEC_USER_AGENT` names the operator and a monitored contact address.
- [ ] Decide the AI setup: model key and default tenant policy, or offline engine only.
- [ ] SMTP configured, or administrators know invitation links are shown to them.
- [ ] Cloud mode: Stripe prices, webhook and customer portal configured and tested in test mode first.
- [ ] Legal pages (`/legal/terms`, `/legal/privacy`, `/legal/ai`) reviewed by counsel and the operator named.
- [ ] Data licenses: no dataset with `licensed` class enabled without a signed agreement.
- [ ] Backups scheduled and a restore drill completed on staging.
- [ ] Third-party penetration test of the staging deployment; critical findings fixed.
- [ ] Compliance review (project definition section 7.5): investment-recommendation rules, EU AI Act
      transparency, GDPR processor agreements with model and payment providers.

## Every release

- [ ] CI green on the commit, including the AI evaluation job.
- [ ] Deployed to staging; smoke test: sign in, chart, ask a question, open evidence, run a backtest.
- [ ] Database backup taken immediately before the production deployment.
- [ ] Production deployed with the same image SHA; health check green; DataLab statuses current.
