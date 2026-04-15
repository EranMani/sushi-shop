# learning_concepts.md — Sushi Shop

> Concepts worth explaining that emerged during the build.
> Only non-obvious or interesting concepts are added — wiring and boilerplate steps skip this.
> Maximum 1–2 concepts per commit step.

---

## Format

Each entry:
- **Commit step:** which protocol step introduced this
- **Concept:** name of the concept
- **Why it matters here:** how it applies specifically to this project (not a generic definition)

---

## Commit 01 — project-foundation

**Concept:** `depends_on` with `condition: service_healthy` vs plain `depends_on`

**Why it matters here:** Plain `depends_on` only waits for the container to *start* — it doesn't wait for the service inside to be *ready*. Postgres starts its container in ~1 second but may take 5–10 seconds to accept connections. Without `condition: service_healthy`, the FastAPI container starts, tries to connect, fails, and crashes — requiring a manual restart or luck with timing. With `condition: service_healthy`, Docker Compose waits until `pg_isready` returns success before starting the `api` container. Every service in this stack uses health checks for this reason.
