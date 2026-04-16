# DECISIONS.md — Sushi Shop

> Non-obvious design and technical choices made during the build.
> Updated at commit time when a choice was made that future contributors would otherwise have to reverse-engineer.
> For architecture-level decisions (system boundaries, data flows), see ARCHITECTURE.md.

---

## Format

Each entry:
- **What:** the decision made
- **Why:** the reasoning — constraints, tradeoffs, alternatives rejected
- **Raised by:** who identified or drove the decision (Eran, Rex, Nova, etc.)

---

## Commit 01 — project-foundation

---

### D-01 · Python 3.12-slim as Dockerfile base image (not Alpine)

**What:** `python:3.12-slim` chosen over `python:3.12-alpine` as the container base.

**Why:** `asyncpg` — the async PostgreSQL driver — requires `gcc` and `musl` headers to compile its C extension on Alpine Linux. Using Alpine would require adding a build toolchain, increasing both image build time and complexity with minimal size saving for this stack. `slim` is smaller than the full image, avoids the Alpine compilation problem, and is the correct tradeoff here.

**Raised by:** Adam (Commit 01)

---

### D-02 · Nginx rate limiting deferred to Commit 15

**What:** The `nginx/nginx.conf` delivered in Commit 01 is a minimal passthrough proxy — upstream and `proxy_pass` only. No `limit_req_zone`, no per-route rules.

**Why:** Rate limiting is a distinct concern assigned to Commit 15 (`nginx-load-balancer-rate-limiter`). Combining it into Commit 01 would violate the one-concern-per-commit protocol. The proxy needs to exist so the stack starts; the rate limiting rules are a separate, purposeful step.

**Raised by:** Adam (Commit 01)

---

### D-02b · uv replacing pip as the container package installer

**What:** `pip install` replaced with `uv pip install` in the Dockerfile. `uv` is pulled via a multi-stage build from the official `ghcr.io/astral-sh/uv:0.6.14` image (pinned tag).

**Why:** `uv` is significantly faster than pip and eliminates the two-step `pip install --upgrade pip && pip install` dance. The binary is pulled via multi-stage `COPY --from` — no curl, no extra OS packages, no pip bootstrap. Tag is pinned so a version bump is an explicit, reviewable change rather than silent drift. `UV_SYSTEM_PYTHON=1` skips venv creation inside the container (the image itself is the isolation boundary). `UV_COMPILE_BYTECODE=1` pre-compiles `.pyc` files at build time for faster startup. Path to full lockfile reproducibility: once `uv.lock` is committed, swap `uv pip install .` for `uv sync --frozen --no-dev`.

**Raised by:** Eran + Adam (post Commit 01 review)

---

### D-03 · Named Docker volumes for Postgres and Redis persistence

**What:** Data volumes are declared as named volumes (`postgres_data`, `redis_data`) rather than bind mounts to a local `data/` directory.

**Why:** Bind mounts to a local directory work, but they pollute the repo root and create git noise (the data directory needs to be gitignored, and any accidental `git add` is a risk). Named volumes are the idiomatic Docker Compose pattern — they persist across `down/up` cycles and are managed by Docker, not the filesystem. `docker-compose down -v` removes them explicitly when a clean state is needed.

**Raised by:** Adam (Commit 01)
