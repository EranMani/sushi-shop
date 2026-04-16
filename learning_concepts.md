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

## entrypoint.sh / PID 1 fix (post Commit 01)

**Concept:** PID 1 and graceful shutdown in Docker containers

**Why it matters here:** Docker sends `SIGTERM` to PID 1 when a container stops. With `CMD ["sh", "-c", "..."]`, `sh` is PID 1 — it may not forward the signal to uvicorn, causing requests to be dropped on deploy or scale-down. Using an `entrypoint.sh` script with `exec uvicorn ...` replaces the shell process with uvicorn, making uvicorn PID 1. It receives `SIGTERM` directly, drains in-flight requests, and exits cleanly. The `exec` keyword is what makes this work — without it, the shell stays as PID 1 even with a script.

---

## uv / pip swap (post Commit 01)

**Concept:** Multi-stage Docker builds for injecting external binaries

**Why it matters here:** `uv` isn't in the Python base image, so to add it without using `pip` or `curl`, Adam used a multi-stage build: `FROM ghcr.io/astral-sh/uv:0.6.14 AS uv-binary`, then `COPY --from=uv-binary /uv /usr/local/bin/uv` in the main stage. The first stage is discarded — only the binary lands in the final image. This pattern is useful any time you need a tool inside a container but don't want to install it via a package manager. The tag is pinned (`0.6.14`, not `:latest`) so a version bump is an explicit, reviewable change.

---

## Commit 02 — database-models

**Concept:** `expire_on_commit=False` in async SQLAlchemy

**Why it matters here:** In sync SQLAlchemy, after a `session.commit()`, all ORM object attributes are marked "expired" and reloaded on next access via a lazy SQL query. In async context, that implicit lazy load raises an error — async SQLAlchemy has no event loop to trigger it on. `expire_on_commit=False` disables the expiry, keeping attributes readable after commit. The tradeoff: if you need guaranteed fresh data after a commit, you must call `session.refresh(obj)` explicitly. This pattern appears throughout Rex's service functions whenever a newly created object is returned to the caller.

---

## Commit 01 — project-foundation

**Concept:** `depends_on` with `condition: service_healthy` vs plain `depends_on`

**Why it matters here:** Plain `depends_on` only waits for the container to *start* — it doesn't wait for the service inside to be *ready*. Postgres starts its container in ~1 second but may take 5–10 seconds to accept connections. Without `condition: service_healthy`, the FastAPI container starts, tries to connect, fails, and crashes — requiring a manual restart or luck with timing. With `condition: service_healthy`, Docker Compose waits until `pg_isready` returns success before starting the `api` container. Every service in this stack uses health checks for this reason.
