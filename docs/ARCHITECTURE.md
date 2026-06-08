# Architecture

## Overview

```
                 HTTP (REST, JSON)
                       │
                ┌──────▼───────┐
                │  internal/api │  auth (api-key→tenant), handlers,
                │   Server      │  request/response shapes
                └──────┬───────┘
            remember →  │  ← conflict decision
                ┌──────▼─────────┐        ┌────────────────────┐
                │ internal/store │        │ internal/conflict   │
                │  Store (iface) │        │  Engine (heuristic  │
                │  SQLite impl   │        │  + optional Resolver)│
                └──────┬─────────┘        └────────────────────┘
                       │
                ┌──────▼───────┐
                │   SQLite      │  memories + memories_fts (FTS5)
                │  (modernc,    │  single file, no CGO
                │   pure Go)    │
                └──────────────┘
```

## Components

### `cmd/memkit`
Entrypoint. Flags/env for listen address, DB path, and API keys. Wires a `Store`, a `conflict.Engine`, and an `api.Server`; runs an `http.Server` with graceful shutdown on SIGINT/SIGTERM.

### `internal/api`
HTTP surface. Bearer-token auth maps an API key to a tenant; every handler is tenant-scoped. Owns request/response DTOs and the **remember** flow that consults conflict-lens before writing. Routing uses the stdlib `http.ServeMux` method+pattern syntax (`POST /v1/memories`, `PUT /v1/memories/{id}`).

### `internal/store`
Persistence contract (`Store` interface) plus the SQLite backend. The interface is small and backend-agnostic so a Postgres implementation drops in without touching the API layer. All methods take `tenant` and scope every query by it — there is no cross-tenant read path.

### `conflict-lens` (external module)
Decides what a new fact *means* relative to existing ones: `add`, `update` (supersede), or `duplicate`. Lives in its own dependency-free module, [`github.com/voltagebots/conflict-lens`](https://github.com/voltagebots/conflict-lens), so it's reusable beyond memkit. Token-overlap heuristic with an optional `Resolver` interface for LLM-backed judgment in the ambiguous band.

## Data model

```sql
memories (
  id            TEXT PRIMARY KEY,   -- 128-bit random hex
  tenant_id     TEXT NOT NULL,      -- from API key
  user_id       TEXT NOT NULL,      -- caller-supplied subject
  content       TEXT NOT NULL,      -- the fact
  category      TEXT NOT NULL,      -- grouping, e.g. "work", "prefs"
  confidence    REAL NOT NULL,      -- 0..1
  metadata      TEXT NOT NULL,      -- JSON blob
  created_at    INTEGER,            -- epoch ms
  last_accessed INTEGER,            -- epoch ms, bumped on recall
  access_count  INTEGER,            -- bumped on recall
  superseded_by TEXT                -- id of replacing fact; NULL = active
)

memories_fts  -- FTS5 mirror (id, tenant_id, user_id, content, category)
              -- porter ascii tokenizer
```

Active facts are `superseded_by IS NULL`. Conflict resolution never deletes — it sets `superseded_by`, preserving full lineage.

## Request flows

### Remember (`POST /v1/memories`)
```
auth → tenant
parse {user_id, content, category, confidence, resolve_conflicts}
sanitize content (strip U+E0000–U+E007F injection tags)
if resolve_conflicts (default true):
    candidates = store.ActiveByCategory(tenant, user, category)
    decision   = conflict.Engine.Resolve(content, candidates)
    ├─ duplicate → Touch(target); return {action:duplicate, id:target}
    ├─ update    → Insert(new); Supersede(target,new); return {action:update, superseded_id}
    └─ add       → fallthrough
Insert(new); return {action:add, id}
```

### Search (`GET /v1/memories/search`)
```
auth → tenant
fts = escape(q)                       -- "phrase" OR prefix* tokens
rows = JOIN memories ⋈ (FTS rank subquery)   -- rank captured before JOIN
       WHERE superseded_by IS NULL           -- active only
score = confidence × timeDecay(last_accessed) × (−ftsRank + accessBoost)
sort desc, trim to limit, Touch each
```

### Scoring
`decay = 1 / (1 + ageDays/30)` (≈half-weight at 30 days). `accessBoost = log(1+access_count)·0.1`. Relevance is the negated FTS5 BM25 rank. Confidence multiplies through.

## Multi-tenancy & isolation
API key → tenant at the edge. Every `Store` method requires `tenant` and filters on it in SQL. The `TestTenantIsolation` test asserts one tenant cannot read another's memories.

## Why these boundaries
- **Store as an interface** → swap SQLite→Postgres at scale with zero API changes.
- **conflict-lens dependency-free** → reusable beyond memkit; testable in isolation; extractable.
- **api owns orchestration** (remember = conflict + store) → store stays a dumb, correct persistence layer; conflict stays pure logic.
