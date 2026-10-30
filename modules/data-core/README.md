# Data Core continuous observation MVP

Python FastAPI local service with separate source/session/build streams, strict 0.1/0.2/0.3 contracts, capture receipts, payload deduplication and SQLite history. It does not read game memory or parse saves; adapters provide observations.

Runtime reception uses server monotonic heartbeat timing, independently from producer capture/observation ages. Connected/stale/disconnected states are visible; an active runtime takes priority over saves, and older captures do not rewind current data. Changes remain low-level UI text/raw-field events without invented football semantics.

Metadata registration exposes inventory completeness separately from verified readability. Records, source evidence and coverage are queryable; registration never invokes a field/property/method/event. Batched counts and coverage are incremental.

`GET /v1/monitoring`, `/v1/events`, `/v1/monitoring/fields` and `/v1/interfaces*` support desktop polling without chat. Events are a future Agent scheduling entry; there is no automatic LLM dispatch. Existing model budget stays unchanged.

Start with `uv run --frozen --extra save --extra agent football-assistant-backend`. See [Backend API](../../docs/backend-api.md) for authentication, protocol details and current limitations. Tests use synthetic fixtures; real continuous-runtime success requires actual bridge captures and separate live verification.
