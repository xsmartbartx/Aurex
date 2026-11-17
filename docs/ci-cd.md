# CI/CD

`.github/workflows/ci.yml` runs on every pull request and on `main`. Any failing stage stops the pipeline.

| Stage | Job | Gate |
|---|---|---|
| Static analysis and architecture check | `static` | ruff lint and format, import-linter contracts, ESLint, TypeScript |
| Dependency and license audit | `audit` | `pip-audit --strict`, `npm audit --audit-level=high`, gitleaks secret scan |
| Validation, unit, integration, isolation, entitlement tests | `tests` | pytest against PostgreSQL 17; coverage ≥ 80% overall and ≥ 90% on critical modules; Vitest; Pester |
| Pentest heuristics, injection corpus, AI evaluation | `evaluation` | `pytest -m eval`; report archived as an artifact |
| Deterministic build and image storage | `build` | Docker images built from locked dependencies, pushed to GHCR on `main` tagged with the commit SHA |

Critical modules for the 90% gate: `core`, `modules/validation`, `security/auth.py`, `security/controls.py`,
`modules/processing`, the claim verifier and DataLab quality rules.

## Environments and release

1. Pull request: all stages.
2. `main`: images `ghcr.io/<repo>/api:<sha>` and `ghcr.io/<repo>/web:<sha>`.
3. Staging: deploy the SHA with the production overlay; run the deployment checklist.
4. Production: the same images after manual approval. Roll back by deploying the previous SHA; database
   migrations are additive, and `scripts/Restore-AurexDatabase.ps1` restores a dump if needed.

No secrets live in the repository. Runtime secrets come from the environment (`.env` on a host, the
platform's secret store elsewhere).
