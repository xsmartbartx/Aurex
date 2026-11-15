# Data flow

## Ingestion

```mermaid
flowchart TD
    S["Scheduler (worker)"] --> F["integration: fetch over https, allow-listed host, paced"]
    F --> V{"Schema valid?"}
    V -- no --> R["Run fails; nothing stored; dataset marked failed"]
    V -- yes --> Q["Quality rules: duplicates, gaps, jumps, non-positive, OHLC consistency"]
    Q --> W["Store a new version only where a value changed"]
    W --> P["Passages screened for instruction-like text"]
    P --> L["Latest values and dataset freshness updated"]
    L --> E["Alerts, thesis monitor, graph refresh"]
```

- A batch is atomic: either every part passes validation or the run stores nothing.
- Quality rules never reject values; they set the status shown with them (`validated`, `suspect`, `demonstration`).
- `known_at` records when a value became known. Where the provider does not state it, a conservative
  publication lag is used (see data-sources.md), so point-in-time reads never see a value too early.
- Three consecutive validation failures from one connector raise a `SECURITY` log event.

## Research question

```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant S as security
    participant W as worker
    participant N as analysis
    participant D as datalab
    participant M as model adapter
    U->>A: question
    A->>S: session, entitlement, daily quota
    A->>W: queue job with record id
    W->>S: rebuild scope, read model policy
    W->>N: run agent with allow-listed tools and budget
    N->>M: plan (external model only if policy allows)
    N->>D: tools read data cleared for this model channel
    N->>N: screen passages, record evidence
    N->>M: draft from evidence
    N->>N: verify each statement, withhold unsupported ones
    W->>A: answer record complete
    U->>A: read answer, open evidence, reproduce
```

The request path is: schema validation (FastAPI/Pydantic) → identity → entitlements and limits →
module logic → output with provenance. Errors use one structure:
`{"error": {"code", "message", "details", "request_id"}}`.
