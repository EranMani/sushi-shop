# Adam's Worklog

## Session Table

| Session | Date | Task | Status | Key decision |
|---|---|---|---|---|
| 001 | 2026-04-15 | project-foundation (Commit 01) | ✅ Done | python:3.12-slim over Alpine — asyncpg build complexity not worth the size saving |

---

## Session 001 — project-foundation

**Date:** 2026-04-15
**Status:** WIP

### Task brief

Building the complete project skeleton for the Sushi Shop. No application logic — this is
the bones everything else will grow on. Goal: a developer can clone this repo, copy `.env.example`
to `.env`, fill in their LLM key, and run `docker-compose up` to get a fully wired stack:
PostgreSQL 16, Redis 7, FastAPI (with health check), Celery worker, and Nginx proxying port 80.

This is Commit 01 — the foundation all other commits depend on. Getting this right means
no one downstream has to work around my choices.

### Decisions

**Decision: Dockerfile entrypoint uses a shell script pattern via CMD, not ENTRYPOINT**
Reason: Using `CMD ["sh", "-c", "alembic upgrade head && uvicorn ..."]` keeps it simple for
Commit 01. The worker override in docker-compose is clean: just replace CMD. No wrapper script
needed at this stage.
Alternatives considered: Separate entrypoint.sh script — adds a file, adds complexity. Not worth
it until we need more startup logic. Could revisit if Rex needs pre-migration hooks.

**Decision: Python 3.12-slim as base image**
Reason: 3.12 is specified in the project stack. Slim variant reduces image size without losing
the packages we actually need. Alpine would save more bytes but has known compatibility issues
with asyncpg (requires gcc + musl headers) — not worth the build complexity.
Alternatives considered: python:3.12-alpine — asyncpg wheel availability on Alpine is unreliable
without build tools; ruled out.

**Decision: Named volumes for Postgres and Redis data**
Reason: `docker-compose down` should not wipe the database. Named volumes persist across
`down/up` cycles. `docker-compose down -v` explicitly removes them when the developer wants
a clean state.
Alternatives considered: Bind mounts to a local `data/` directory — works, but pollutes the
repo root and creates git noise. Named volumes are the correct pattern.

**Decision: Nginx config for Commit 01 is minimal — no rate limiting**
Reason: Commit 15 owns `nginx-load-balancer-rate-limiter`. The task brief confirms: "No rate
limiting yet (that's Commit 15). Must be functional enough for the stack to start and route
traffic." I'm delivering exactly that — a working upstream and proxy_pass. Commit 15 will
extend this with `limit_req_zone` and the per-IP rules.
Alternatives considered: Adding rate limiting now — violates one-concern-per-commit protocol.

**Decision: CI test job spins up both postgres AND redis as GitHub Actions services**
Reason: Even though Commit 01 has no tests, the CI infrastructure needs to be ready for
the test suite that starts at Commit 16. Rex will need both services available. Setting up
the services now means he can write tests without touching the CI config.
Alternatives considered: Only postgres in CI for now — creates a Commit 16 dependency on
returning to adam.md territory. Better to do it right once.

**Decision: pyproject.toml uses `[project.optional-dependencies]` for dev/test deps**
Reason: Standard PEP 621 pattern. `pip install -e ".[dev]"` installs test deps. Production
image installs only the base dependencies — keeps the image lean.
Alternatives considered: requirements.txt + requirements-dev.txt — works but not idiomatic
for a pyproject.toml-first project. Consistency matters.

**Decision: health check for FastAPI container uses wget not curl**
Reason: Python slim images include wget but not curl. Using `wget -q --spider http://localhost:8000/health`
avoids installing an extra package. Redis health check uses `redis-cli ping` (included in
the redis image). Postgres uses `pg_isready` (included in postgres image).

**Decision: Makefile `migrate` and `shell` targets run inside the running `api` container**
Reason: `docker-compose exec api` is the correct pattern — it reuses the running container
rather than spinning up a new one. The developer must have `make up` running first, which
is the intended workflow.

### Issues found

None — this is a clean-slate commit with no pre-existing code to conflict with.

### Handoff notes

## Handoff → Rex

What changed: Complete project skeleton is in place. All directory structures created,
all Python package `__init__.py` files in place, `pyproject.toml` with all runtime and
dev dependencies, `src/main.py` with the bare FastAPI app and `GET /health` route.

What Rex needs to know:
- `src/main.py` is a skeleton only. Rex takes ownership from Commit 02 onward.
- All runtime dependencies are declared in `pyproject.toml` under `[project.dependencies]`.
  If Rex needs to add a dependency, he should update `pyproject.toml` and send a handoff
  to Adam so the container config can be updated if needed.
- `DATABASE_URL` and `REDIS_URL` env vars are declared in `.env.example`. The async
  postgres URL format is `postgresql+asyncpg://...` — already set in the example.
- `TEST_DATABASE_URL` points to the `sushi_test` database defined in `docker-compose.test.yml`.
- `alembic upgrade head` runs automatically on container start (in the CMD). Rex should
  ensure his migrations are idempotent — running them twice should be safe.
- The `worker` service uses the same image with CMD overridden to:
  `celery -A src.core.celery_app worker --loglevel=info`
  Rex needs to make `src.core.celery_app` importable and expose the `celery_app` Celery instance.

Files to read: `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `.env.example`, `src/main.py`
I'm done. You can start.

### Self-review checklist

- [x] All five services in docker-compose.yml with health checks
- [x] Health checks: pg_isready (postgres), redis-cli ping (redis), wget /health (api)
- [x] api and worker depend_on db and redis with condition: service_healthy
- [x] nginx depends_on api being healthy
- [x] Named volumes for postgres and redis data persistence
- [x] .env is gitignored, .env.example has placeholders only
- [x] alembic upgrade head runs before uvicorn in the container CMD
- [x] Worker CMD uses same image, different command
- [x] All src/ __init__.py files created
- [x] pyproject.toml has all runtime + dev deps
- [x] .github/workflows/ci.yml: lint + test jobs, pip cache, services
- [x] Makefile: up, down, logs, migrate, test, worker, shell targets
- [x] Nginx: upstream to api:8000, proxy_pass on port 80
- [x] docker-compose.test.yml: db_test service with sushi_test database
- [x] .dockerignore excludes .git, __pycache__, *.pyc, .env, .pytest_cache, *.egg-info

### Documentation flags for Claude

📋 Documentation flags for Claude:

- ARCHITECTURE.md: Add "Infrastructure layer" section describing the five Docker Compose
  services (db, redis, api, worker, nginx), their health check strategy, and startup
  ordering (depends_on with condition: service_healthy). Note that api and worker share
  the same image — differentiated only by CMD. Note Alembic runs on container start.

- DECISIONS.md: Record "Python 3.12-slim chosen over Alpine for asyncpg compatibility —
  Alpine requires gcc and musl headers to compile asyncpg wheel; slim avoids build
  complexity without meaningful size penalty for this stack."

- DECISIONS.md: Record "Nginx rate limiting deferred to Commit 15 — Commit 01 delivers
  a functional proxy only. Rate limiting is a separate concern (Commit 15) and combining
  would violate the one-concern-per-commit protocol."

- DECISIONS.md: Record "Named Docker volumes for Postgres and Redis — bind mounts to a
  local data/ directory were considered but create git noise; named volumes are the
  idiomatic Docker Compose pattern for persistent service data."

- GLOSSARY.md: Confirm "DLQ (Dead Letter Queue)" is defined (used in commit-protocol.md)
  and add if missing.

---

**Status:** ✅ Done — all 26 files written, self-review passed, handoff to Rex recorded above.
