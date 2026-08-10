# memkit

Self-hostable memory layer for AI agents. A single Go binary, SQLite-backed, with **conflict resolution built in** — so your agent remembers what's *true*, not just what's *similar*.

```
go run ./cmd/memkit          # starts on :8080 with a dev key
```

No cloud account. No Python runtime. No external services. `go build` → one static binary you own.

## Why

Vector/keyword recall measures **similarity, not truth**. "I love my job" (week 1) and "I quit" (week 2) both mention the job and retrieve together — a naive agent hallucinates a synthesis. memkit classifies the *relationship* between a new fact and what's already known, and **supersedes** the stale fact (keeping it as history) instead of accumulating contradictions.

| | memkit | mem0 | Letta | Zep |
|---|---|---|---|---|
| Self-host, single binary | ✅ | ⚠️ cloud-first | ⚠️ heavy | ⚠️ |
| No Python runtime | ✅ Go | ❌ | ❌ | — |
| Conflict resolution built in | ✅ | partial | partial | ✅ |
| License | MIT | — | — | commercial (prod) |

## API

All endpoints require `Authorization: Bearer <api-key>` (maps to a tenant). All data is scoped by tenant + `user_id`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/memories` | Remember a fact; conflict-lens runs on write (returns `add` / `update` / `duplicate`) |
| `GET` | `/v1/memories/search?user_id=&q=&category=&limit=` | Ranked recall (relevance × time-decay), active facts only |
| `PUT` | `/v1/memories/{id}` | Explicitly supersede a fact with a correction |
| `DELETE` | `/v1/memories/{id}` | Hard-delete a fact |
| `DELETE` | `/v1/users/{user_id}` | GDPR erasure — purge all of a user's memories |
| `GET` | `/v1/categories?user_id=` | List categories with counts |
| `GET` | `/healthz` | Liveness |

### Remember with automatic conflict resolution

```bash
curl -XPOST localhost:8080/v1/memories -H "Authorization: Bearer dev-key" \
  -d '{"user_id":"u1","content":"User works at Google","category":"work"}'
# → {"id":"…","action":"add"}

curl -XPOST localhost:8080/v1/memories -H "Authorization: Bearer dev-key" \
  -d '{"user_id":"u1","content":"User works at OpenAI","category":"work"}'
# → {"id":"…","action":"update","superseded_id":"…","reason":"high overlap with differing detail…"}
```

Search now returns only the active fact (OpenAI); Google is archived, not lost.

Set `"resolve_conflicts": false` to store verbatim without conflict-lens.

## Configuration

| Env | Default | Description |
|---|---|---|
| `MEMKIT_ADDR` | `:8080` | Listen address |
| `MEMKIT_DB` | `memkit.db` | SQLite path (`:memory:` for ephemeral) |
| `MEMKIT_API_KEYS` | `dev-key:default` | `key1:tenant1,key2:tenant2` |
| `MEMKIT_CONSOLIDATE_INTERVAL` | `1h` | How often the maintenance loop runs |
| `MEMKIT_SUPERSEDED_RETENTION` | `720h` | Archived (superseded) facts older than this are pruned |
| `MEMKIT_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | _(unset)_ | Enables the Claude conflict resolver |
| `MEMKIT_RESOLVER_MODEL` | `claude-haiku-4-5-20251001` | Model for the resolver |

## Docker

```bash
docker build -t memkit .
docker run -p 8080:8080 -v memkit-data:/data -e MEMKIT_API_KEYS="prod-key:acme" memkit
```

Static binary on `distroless/static` as non-root (uid 65532). The DB lives at `/data/memkit.db` — mount a volume to persist it.

## Maintenance

A background loop prunes superseded facts older than `MEMKIT_SUPERSEDED_RETENTION`, keeping the store lean while recent history stays queryable. Read-time recency *decay* is separate (in search scoring). Tune cadence with `MEMKIT_CONSOLIDATE_INTERVAL`.

## conflict-lens

The conflict engine is its own dependency-free module — [`github.com/agent-rails/conflict-lens`](https://github.com/agent-rails/conflict-lens) — so it's reusable outside memkit. It applies a token-overlap heuristic (add / update / duplicate) with an optional `Resolver` hook for LLM-grade semantic resolution of ambiguous cases. See [docs/DESIGN.md](docs/DESIGN.md).

### Claude resolver (optional)

Set an Anthropic API key and memkit attaches a Claude-backed resolver and widens the conflict band so short/ambiguous facts are sent for semantic judgment — closing the lexical blind spot ("I love my job" → "I hate my job"). The resolver is consulted **only** for borderline cases (clear adds/duplicates/conflicts stay on the free heuristic), the system prompt is prompt-cached, and it uses a small fast model. On any API error the engine falls back to the heuristic. Implementation: [`internal/resolver`](internal/resolver).

## Use from Claude Code / any MCP client

`cmd/memkit-mcp` is a dependency-free stdio **MCP bridge** so an MCP client can use memkit as its long-term memory (tools: `remember`, `recall`, `update_memory`, `forget`, `list_categories`).

```bash
go build -o memkit-mcp ./cmd/memkit-mcp

# point an MCP client at it (Claude Code shown):
claude mcp add memkit --scope user \
  -e MEMKIT_URL=http://localhost:8420 \
  -e MEMKIT_API_KEY=your-key \
  -e MEMKIT_USER=you \
  -- /path/to/memkit-mcp
```

The bridge talks to a running memkit server over REST; run one (see Docker above or `go run ./cmd/memkit`). On macOS, a launchd agent keeps memkit always-on — see [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data model, request flows
- [docs/DESIGN.md](docs/DESIGN.md) — the *why*: decisions, trade-offs, alternatives, limitations

## Status

v0.1 — REST + SQLite + conflict-lens (heuristic + optional LLM resolver), consolidation/decay cron, conflict-lens extracted as its own module. Roadmap: Postgres backend, gRPC, embedding-backed recall.

Built on the model proven in [memory-mcp](https://github.com/voltagebots/memory-mcp) (the TypeScript MCP prototype).

## License

MIT
