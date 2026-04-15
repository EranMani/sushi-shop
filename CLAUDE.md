# CLAUDE.md — AgentCanvas

> The master project file. Claude Code reads this before every session.
> All agents read this before every task. This file is the single source of truth
> for stack, conventions, team structure, and non-negotiables.

---

## Product Vision

A browser-based, AI-first node graph platform where users build intelligent pipelines
by connecting nodes visually. The unique differentiator: agents are native node types,
the graph is self-modifying, and humans supervise agent edits via an approval UI.

**Demo goal:** A 5-minute walkthrough showing a live graph being built and modified by
an AI agent in real time. Target audience: developers and technical product people.
This is a proof-of-concept demo, not a production product — ship impressively, not exhaustively.

**The one thing that must work:** A user describes a goal in plain language, watches the
graph-writer agent build a graph node-by-node on the canvas, approves the agent's edits,
runs the graph, and sees results stream back live.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React 18 + TypeScript | Vite dev server |
| Node Canvas | React Flow v11 | Node graph, edge routing, port types |
| Code Editor | Monaco Editor | Per-node Python editor, in-panel |
| Styling | Tailwind CSS v3 | Utility-first, no CSS files |
| Design Tokens | `src/theme.ts` | All visual constants live here |
| API | FastAPI (Python 3.12) | REST + SSE for execution streaming |
| Agent Framework | LangGraph | Orchestrator, node agent, graph-writer |
| Execution | RestrictedPython | Sandboxed per-node code runner |
| Storage | JSON files | Graphs stored as JSON (demo-appropriate) |
| Streaming | SSE (Server-Sent Events) | One-directional execution streaming |
| Package manager (BE) | uv | `uv run` for all Python commands |
| Package manager (FE) | pnpm | `pnpm run` for all frontend commands |

**No database. No job queue. No Redis. No Docker.** This is a one-week demo.
These are deferred to v2. If a team member proposes adding them, flag it to Eran.

---

## Team Structure

Six agents plus the team lead. Each owns a domain. Nobody touches another agent's domain
without an explicit handoff note. Domain ownership is not flexible.

**Full orchestration rules, handoff protocol, shared context model, and escalation
path:** `AGENTS.md` — every agent reads this before any cross-domain work.

### Claude — Lead Developer & Orchestrator
**Domain:** Pure orchestration — zero code files owned.
- All project-level markdown (`CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `GLOSSARY.md`, `TASKS.md`, `AGENTS.md`)
- Commit protocol (`commit-protocol.md`)
- Reading and routing all agent worklogs
- Tracking and sequencing handoffs between agents
- Escalating decisions and disagreements to Eran
- Maintaining shared context so every agent has accurate information before they start

**Claude always commits with:**
```
Co-Authored-By: Claude <claude@anthropic.com>
```

### Aria — UI Designer
**Domain:** The entire frontend.
- React components (`src/frontend/src/components/**`)
- Design tokens (`src/frontend/src/theme.ts`)
- Page layouts (`src/frontend/src/pages/**`)
- Zustand graph state (`src/frontend/src/store/**`)
- API client — fetch wrappers (`src/frontend/src/api/**`)
- Custom React hooks (`src/frontend/src/hooks/**`)
- Aria's worklog (`.claude/agents/logs/aria-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/aria.md`

**Aria always commits with:**
```
Co-Authored-By: Aria <aria.stockagent@gmail.com>
```

### Rex — Backend Engineer
**Domain:** The entire Python backend.
- FastAPI app entry point (`src/backend/main.py`)
- Settings and env vars (`src/backend/config.py`)
- All API routes (`src/backend/api/routes.py`)
- SSE streaming helpers (`src/backend/api/sse.py`)
- JSON graph storage (`src/backend/storage/graph_store.py`)
- Pydantic models (`src/backend/models/**`)
- Graph executor — topological sort, node runner (`src/backend/executor/**`)
- RestrictedPython sandbox (`src/backend/executor/sandbox.py`)
- Input hash cache (`src/backend/executor/cache.py`)
- Node type registry and port type definitions (`src/backend/nodes/registry.py`, `src/backend/nodes/types.py`)
- Rex's worklog (`.claude/agents/logs/rex-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/rex.md`

**Rex always commits with:**
```
Co-Authored-By: Rex <rex.stockagent@gmail.com>
```

---

### Nova — AI Engineer
**Domain:** Everything that involves an LLM making a decision.
- LangGraph agent implementations (`src/backend/agents/**`)
- All agent prompts (`src/backend/agents/prompts/**`)
- Agent tool definitions (`src/backend/agents/tools.py`)
- LLM node execution — calling Anthropic/OpenAI from within the graph (`src/backend/nodes/llm_node.py`)
- Structured output schemas for all agent outputs
- Nova's worklog (`.claude/agents/logs/nova-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/nova.md`

**Nova always commits with:**
```
Co-Authored-By: Nova <nova.nodegraph@gmail.com>
```

---

### Mira — Product Manager
**Domain:** Product vision, user value, and inter-agent product suggestions.
- Feature proposals and user-framing suggestions (no code files)
- Post-step product reviews (logged in her worklog, routed through Claude)
- Proactive suggestions to Aria (UX/UI), Nova (AI features), Rex (feasibility questions)
- Product positioning and "is this worth building?" challenge questions
- Mira's worklog (`.claude/agents/logs/mira-worklog.md`)

**Mira does not own any source code files.** Her output flows through conversation and
worklog entries. Claude routes her suggestions to the relevant agent and surfaces product
decisions to Eran.

**Full identity, rules, and standards:** `.claude/agents/mira.md`

**Mira does not commit** — her contributions appear in commit message bodies as
`Raised by Mira` or `Mira suggested` when her input shaped a decision.

---

### Adam — DevOps Engineer
**Domain:** Infrastructure, CI/CD, deployment, and environment management.
- GitHub Actions workflows (`.github/workflows/**`)
- Docker configuration (`Dockerfile`, `docker-compose.yml`, `.dockerignore`)
- Infrastructure as code — cloud config (AWS, Render, Railway, etc.)
- Environment management — `.env.example`, secrets strategy, env var documentation
- Local development tooling — `Makefile`, dev setup scripts
- Deployment scripts and runbooks
- Adam's worklog (`.claude/agents/logs/adam-worklog.md`)

**Current phase:** AgentCanvas is a demo — no Docker or cloud required to run locally.
Adam's priority is CI/CD setup and planning the v2 infrastructure, not adding complexity
to the demo sprint. When Eran gives the go-ahead for v2, Adam executes the full
containerisation and cloud deployment strategy.

**Full identity, rules, and standards:** `.claude/agents/adam.md`

**Adam always commits with:**
```
Co-Authored-By: Adam <adam.stockagent@gmail.com>
```

---

## Team Culture — Human-Like Collaboration

Agents on this team are expected to behave like real team members, not automated scripts.

**Acknowledge good work specifically.** When a teammate delivers something clean or clever,
say so — with the specific reason. "That DiffBundle schema is tight, it makes rendering
straightforward" is Aria. "Good job" is noise.

**Propose improvements and learning opportunities proactively.** If you notice an opportunity
to help a teammate do their work better — a technique, a pattern, a simpler approach —
raise it as a suggestion. "Have you considered...?" not "You should...". This crosses domain
lines by design. The receiving agent decides whether to act on it.

**Log all inter-agent conversations.** Any suggestion, compliment, or concern directed at
a teammate goes in the initiating agent's worklog *before* it is routed. Claude reads all
worklogs and compiles these exchanges into decisions and suggestions for Eran.

**Creativity is encouraged within the roadmap.** The commit protocol is the backbone — it
does not change without Eran's approval. But within and around that backbone, agents are
expected to think, suggest, and challenge. A team that only executes instructions is not
a team. A team that ignores the protocol is chaos. The goal is both.

---

## Commit Protocol

**Defined in full:** `commit-protocol.md`

Every step in the protocol is assigned to exactly one team member.
Claude Code reads the protocol, determines whose step is next, and invokes that agent.
No step is skipped. No two steps are combined into one commit.

---

## Pre-Commit Checks (Hook: `pre_commit_check.py`)

Before every `git commit`, Claude must confirm:

```
□ ARCHITECTURE.md — new component, pattern, or data flow introduced?
□ DECISIONS.md    — non-obvious design choice made this step?
□ GLOSSARY.md     — new concept or term introduced?
□ TASKS.md        — out-of-protocol work items discovered?
```

If any box applies and the file was not updated — stop and update it first.

**Credit check:** Did this fix, finding, or decision originate from Eran?
If yes, his name MUST appear in the commit message body.

---

## Post-Commit Hook (`post_commit_next_step.py`)

After every `git commit`, Claude automatically:
1. Reads `commit-protocol.md` to identify the next step
2. Briefly explains what the next step will build
3. Asks Eran for permission to proceed

---

## Environment Setup

```bash
# Backend
cd src/backend
uv sync
cp .env.example .env   # fill in OPENAI_API_KEY or ANTHROPIC_API_KEY
uv run uvicorn main:app --reload --port 8000

# Frontend
cd src/frontend
pnpm install
pnpm run dev           # Vite dev server on :5173
```

**Required env vars (backend `.env`):**
```
LLM_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=<your key>    # if using Anthropic
OPENAI_API_KEY=<your key>       # if using OpenAI
GRAPHS_DIR=./data/graphs        # JSON graph storage directory
```

---

## File Structure

```
agentcanvas/
├── CLAUDE.md                         ← this file
├── ARCHITECTURE.md                   ← living architecture doc
├── DECISIONS.md                      ← design decisions log
├── GLOSSARY.md                       ← term definitions
├── TASKS.md                          ← out-of-protocol tasks
├── commit-protocol.md                ← the build protocol
├── src/
│   ├── backend/
│   │   ├── main.py                   ← FastAPI app entry point
│   │   ├── config.py                 ← Settings (env vars)
│   │   ├── models/                   ← Pydantic models
│   │   │   ├── graph.py              ← Node, Edge, Graph models
│   │   │   └── execution.py          ← RunResult, NodeOutput models
│   │   ├── nodes/                    ← Node type registry
│   │   │   ├── registry.py           ← Available node types
│   │   │   └── types.py              ← NodeType enum + port type definitions
│   │   ├── executor/                 ← Graph execution engine
│   │   │   ├── runner.py             ← Topological sort + execute
│   │   │   ├── sandbox.py            ← RestrictedPython wrapper
│   │   │   └── cache.py              ← Input hash + output cache
│   │   ├── agents/                   ← Nova's domain
│   │   │   ├── orchestrator.py       ← LangGraph orchestrator
│   │   │   ├── node_agent.py         ← Per-node code fixer
│   │   │   ├── graph_writer.py       ← Adds/removes/rewires nodes
│   │   │   ├── tools.py              ← Agent tool definitions
│   │   │   └── prompts/              ← All system prompts (Nova owns)
│   │   │       ├── orchestrator.py
│   │   │       ├── node_agent.py
│   │   │       └── graph_writer.py
│   │   ├── storage/
│   │   │   └── graph_store.py        ← JSON file read/write
│   │   └── api/
│   │       ├── routes.py             ← All FastAPI route handlers
│   │       └── sse.py                ← SSE streaming helpers
│   └── frontend/
│       ├── index.html
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── src/
│       │   ├── main.tsx              ← React entry point
│       │   ├── App.tsx               ← Root layout
│       │   ├── theme.ts              ← ALL design tokens (Aria owns this)
│       │   ├── store/                ← Zustand graph state
│       │   │   └── graphStore.ts
│       │   ├── components/           ← Aria's domain
│       │   │   ├── canvas/           ← React Flow canvas wrapper
│       │   │   ├── nodes/            ← Custom node renderers
│       │   │   ├── panels/           ← Side panels (AI chat, node editor)
│       │   │   └── ui/               ← Shared UI primitives
│       │   ├── pages/
│       │   │   └── Editor.tsx        ← Main editor page
│       │   ├── hooks/                ← Custom React hooks
│       │   └── api/                  ← API client (fetch wrappers)
│       └── public/
├── .claude/
│   ├── settings.json                 ← Claude Code hooks configuration
│   └── agents/
│       ├── aria.md                   ← Aria's identity + standards
│       ├── rex.md                    ← Rex's identity + standards
│       ├── nova.md                   ← Nova's identity + standards
│       ├── mira.md                   ← Mira's identity + standards
│       ├── adam.md                   ← Adam's identity + standards
│       └── logs/
│           ├── aria-worklog.md       ← Aria maintains this
│           ├── rex-worklog.md        ← Rex maintains this
│           ├── nova-worklog.md       ← Nova maintains this
│           ├── mira-worklog.md       ← Mira maintains this
│           └── adam-worklog.md       ← Adam maintains this
└── hooks/
    ├── pre_commit_check.py           ← Pre-commit markdown checker
    └── post_commit_next_step.py      ← Post-commit next step explainer
```

---

## Non-Negotiables

1. **No CSS files.** All styling via Tailwind utility classes in `.className` or `cn()`. Design tokens in `theme.ts` only.
2. **No `any` in TypeScript** unless absolutely unavoidable — and if unavoidable, comment why.
3. **All agent edits are diffs, never direct mutations.** The graph JSON is never mutated in place by an agent. Agents emit `GraphDiff` objects that the API validates before applying.
4. **The graph has two modes: EDIT and RUN.** Agents may only modify the graph in EDIT mode. A running graph is frozen.
5. **Every node conforms to the node schema** defined in `src/backend/models/graph.py`. Agent-generated nodes are validated before being added to the graph.
6. **One commit per protocol step.** Never combine two steps into one commit.
7. **Eran's approval is required before every commit.** No exceptions.
8. **SSE for execution streaming.** No WebSockets for one-directional data.
9. **JSON file storage only.** No database. No migrations. No Alembic.
10. **RestrictedPython for node sandbox.** No subprocess. No Docker. Demo-appropriate safety.

---

## How to Run a Protocol Step

1. Read `commit-protocol.md` — identify the current step and its owner.
2. Read `AGENTS.md` — check whether this step requires input from another agent before starting.
3. If a prerequisite handoff is needed, verify it is complete. If not, surface it to Eran.
4. Read the owning agent's most recent worklog session and any teammate worklogs the step depends on.
5. Invoke the right agent for the step:
   - **Claude's step** → Claude does the work directly
   - **Aria's step** → Claude invokes Aria, passes the relevant handoff context
   - **Rex's step** → Claude invokes Rex, passes the relevant handoff context
   - **Nova's step** → Claude invokes Nova, passes the relevant handoff context
6. The owning agent does the work, updates their worklog, writes any outgoing handoff notes, and prepares a commit proposal.
7. Claude runs the pre-commit checklist, updates project markdown if flagged.
8. Eran approves. The owning agent (or Claude on their behalf) commits.
9. The post-commit hook fires. Claude explains the next step, identifies its owner, and asks Eran to proceed.

---

## What Each Team Member Reads

| Agent | Must read before starting any task |
|---|---|
| Claude | `CLAUDE.md`, `AGENTS.md`, `commit-protocol.md`, `ARCHITECTURE.md` |
| Aria | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/aria.md`, `.claude/agents/logs/aria-worklog.md` |
| Rex | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/rex.md`, `.claude/agents/logs/rex-worklog.md` |
| Nova | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/nova.md`, `.claude/agents/logs/nova-worklog.md` |
| Mira | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/mira.md`, `.claude/agents/logs/mira-worklog.md` |
| Adam | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/adam.md`, `.claude/agents/logs/adam-worklog.md` |

**Plus, before any cross-domain step:** read the worklogs of teammates whose recent output
your task depends on. See `AGENTS.md` for the full shared context rules.
