# Design

## Goal

A memory layer any team can self-host as a single binary, that resolves contradictions instead of hoarding them. The differentiator vs the field is *ownership + conflict handling*, not raw retrieval.

## Key decisions (the why)

### Go, single static binary
- Matches the maintainer's stack (the vigilo daemon is Go) and the "you own it" pitch: `go build` → one file, drop it on a box, done. No interpreter, no service mesh.
- Good concurrency story for a multi-tenant API.
- Contrast: mem0/Letta are Python (runtime + deps to manage); the whole point here is operational simplicity.

### Pure-Go SQLite (`modernc.org/sqlite`), not CGO
- A CGO SQLite (e.g. mattn) would break the single-static-binary promise and complicate cross-compilation. `modernc.org/sqlite` is pure Go and ships FTS5.
- SQLite is the *default*, not the ceiling — the `Store` interface exists so Postgres is a drop-in for multi-node deployments. We start simple and scale by swapping the backend, not rewriting the app.

### FTS5 keyword search before embeddings
- Zero-config, no API key, no model download — preserves the "just run it" experience.
- Honest limitation: keyword recall can't match "statically typed language" to "TypeScript". Embedding-backed recall is roadmapped as an *opt-in*, not a hard dependency.
- The BM25 `rank` is captured in a subquery before the JOIN, because FTS5's hidden `rank` column returns 0 when read through a JOIN alias. (Learned in the memory-mcp prototype; carried over.)

### Conflict resolution by supersession, not deletion
This is the reason the project exists. When a new fact contradicts an old one, the old row's `superseded_by` is set and only active facts surface in recall. The old fact remains as queryable history.
- **vs. storing both** → that's the bug: recall returns "works at Google" *and* "works at OpenAI" and the agent invents a synthesis.
- **vs. hard delete + reinsert** → loses lineage; you can't answer "where did they work before?"
- **vs. an `active` boolean** → `superseded_by` carries strictly more information (which fact replaced it) at the same cost.

### conflict-lens: heuristic core, optional LLM Resolver
The engine compares a new fact's tokens against existing active facts in the same category (Jaccard overlap):

```
overlap ≥ 0.85            → duplicate (skip)
0.45 ≤ overlap < 0.85     → conflict  (supersede the closest)  ← Resolver consulted here if set
overlap < 0.45            → add       (new information)
```

Intuition: facts about the *same thing* share most words and differ in the changed value ("works at **Google**" → "works at **OpenAI**", overlap ≈0.67). Different facts share few words.

**Why a heuristic and not always an LLM:** an LLM call per write doesn't scale and re-does judgment the calling agent already has context for. The cheap heuristic handles the common, clear cases (employer/location/status changes in descriptive facts) at zero marginal cost; the `Resolver` hook is there for teams that want LLM-grade resolution in the ambiguous band.

**Known limitation — short antonym flips.** For very short facts where the changed word is most of the content, lexical overlap can't distinguish a contradiction from an addition:
- "I love my job" → "I hate my job" (contradiction)
- "User likes Python" → "User likes Rust" (addition — you can like both)

Both score ≈0.33. The bare heuristic conservatively treats this band as **add** (never wrongly erase a fact). Resolving it correctly *requires semantics* — which is exactly the `Resolver`'s job. This is documented and tested (`TestResolve_ShortAntonym_*`) rather than papered over by lowering the threshold, which would cause wrong supersessions of additive facts.

### Tenancy at the edge, isolation in SQL
API key → tenant in the auth wrapper; every `Store` method takes `tenant` and filters on it. No handler can construct a cross-tenant query. Enforced by `TestTenantIsolation`.

### Injection-safe writes
Stored memories later flow into LLM prompts, so the Unicode tag block (U+E0000–U+E007F) — an invisible instruction-smuggling vector — is stripped on write. (Pattern from the goose agent framework.)

### GDPR erasure as a first-class endpoint
`DELETE /v1/users/{id}` purges a user across base table and FTS in one transaction. Data-subject deletion is a requirement, not an afterthought, for anything storing personal context.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| mem0 / Letta / Zep | Cloud-first, Python-heavy, or commercial-for-prod — none give an owned single binary |
| CGO SQLite (mattn) | Breaks static binary + easy cross-compile |
| Embeddings in core | Adds an API key / model dependency; kills zero-config. Opt-in later |
| gRPC first | REST is enough to validate; gRPC added once the contract stabilizes |
| Always-LLM conflict | Cost + latency per write; doesn't scale |

## Known limitations
1. Keyword (not semantic) recall — see embeddings roadmap.
2. Short antonym contradictions need the Resolver (above).
3. SQLite single-writer — fine for self-host scale; Postgres backend for high concurrency.
4. API keys are static config — fine to start; DB-backed tenant/key management later.

## Roadmap
| Version | Change |
|---|---|
| v0.1 | REST + SQLite + conflict-lens (heuristic), multi-tenant, GDPR purge |
| v0.2 | Consolidation/decay cron; `confidence`-aware ranking polish; metrics |
| v0.3 | Postgres backend; embedding-backed recall (opt-in); LLM `Resolver` impl |
| v0.4 | gRPC API; extract `conflict-lens` into its own module |
| v1.0 | Multi-node, replication, hardening |
