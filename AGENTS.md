# AGENTS.md — Sushi Shop

> Full orchestration rules, handoff protocol, shared context model, and escalation path.
> Every agent reads this before any cross-domain work. CLAUDE.md is the what — this file is the how.

---

## The Team

| Agent | Role | Code domain |
|---|---|---|
| **Claude** | Lead Developer & Orchestrator | No code — markdown and routing only |
| **Rex** | Backend Engineer | `src/` (except `src/agents/` and `src/api/routes/agent.py`) |
| **Nova** | AI Engineer | `src/agents/`, `src/api/routes/agent.py` |
| **Adam** | DevOps Engineer | `Dockerfile`, `docker-compose*.yml`, `nginx/`, `.env.example`, `Makefile`, `.github/` |
| **Mira** | Product Manager | No code — worklog and suggestions only |
| **Aria** | UI Designer | No code yet — frontend phase not started |

Domain ownership is absolute. No agent edits files outside their domain without an
explicit handoff and Eran's awareness. If you discover a problem in another agent's
domain — log it and flag it. Do not fix it yourself.

---

## How a Protocol Step Works

```
1. Claude reads commit-protocol.md — identifies the current step and its owner
2. Claude reads the owning agent's most recent worklog session
3. Claude reads any prerequisite handoff notes from teammate worklogs
4. Claude invokes the owning agent with the handoff context
5. The owning agent does the work and updates their worklog continuously
6. The owning agent writes outgoing handoff notes for any teammates whose next step
   depends on decisions made in this step
7. Claude runs the pre-commit checklist (ARCHITECTURE.md, DECISIONS.md, GLOSSARY.md)
8. Eran approves
9. The owning agent (or Claude on their behalf) commits
10. Claude identifies the next step and asks Eran to proceed
```

No step is skipped. No two steps are combined. Eran approves every commit.

---

## Shared Context Rules

Before starting any task, every agent must read:

| Agent | Required reading |
|---|---|
| Claude | `CLAUDE.md`, `AGENTS.md`, `commit-protocol.md`, `ARCHITECTURE.md` |
| Rex | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/rex.md`, `.claude/agents/logs/rex-worklog.md` |
| Nova | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/nova.md`, `.claude/agents/logs/nova-worklog.md` |
| Adam | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/adam.md`, `.claude/agents/logs/adam-worklog.md` |
| Mira | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/mira.md`, `.claude/agents/logs/mira-worklog.md` |

**Plus, for any cross-domain step**, read the worklogs of teammates whose recent output
your task depends on. The dependency map:

| If you are... | Also read before starting |
|---|---|
| Nova (building tools) | Rex's worklog — your tools call his services |
| Rex (changing a service interface) | Nova's worklog — she may have tools depending on the current signature |
| Adam (updating containers or env vars) | Rex's worklog — his new deps or env vars may need container changes |
| Nova (adding a new env var for LLM config) | Adam's worklog — he manages `.env.example` |

Reading worklogs is not optional. Decisions that constrain your work are recorded there,
not in the code.

---

## Handoff Protocol

A handoff note is required whenever your completed work creates a dependency that
another agent must be aware of before they can start their next step.

**When to write a handoff:**
- You changed a function signature that another agent's code calls
- You added a new API route that another agent's tool uses
- You added a new env var that Adam needs to add to `.env.example`
- You added a new Python dependency that Adam needs to add to the container
- You changed a Pydantic schema that is used as a tool output or API response

**Where to write it:** At the bottom of your current worklog session, clearly labelled.

**Standard format:**
```
## Handoff → [Agent name]

What changed: [one paragraph — what you built or modified]
What they need to know:
- [specific field, type, or signature change]
- [any constraint or invariant they must preserve]
- [any error case they need to handle]
Files to read: [list the specific files]
I'm done. You can start.
```

**Standard Rex → Nova handoff** (after services or routes are finalised):
```
## Handoff → Nova

What I built: [service name or route]
Service function signatures: [name(params) → return type]
Route: [METHOD /path — request schema → response schema]
Error cases: [what is raised and when — Nova's tools must handle these]
Files to read: src/services/[name].py, src/api/routes/[name].py
I'm done. You can start.
```

**Standard Rex → Adam handoff** (after adding deps or env vars):
```
## Handoff → Adam

What changed: [new package / new env var / new port / changed startup command]
Why it matters for the container: [one sentence]
What you need to update: [docker-compose.yml / .env.example / Dockerfile]
Files to read: pyproject.toml, src/core/settings.py
I'm done. You can start.
```

**Standard Nova → Claude handoff** (after agent and tools are complete):
```
## Handoff → Claude

What the agent does: [one paragraph]
Agent route: POST /agent/chat — [request shape → response shape]
Tools registered: [tool name — what it does, one line each]
Error states: [what the agent returns on LLM failure / tool failure]
Files to read: src/agents/graph.py, src/agents/tools.py, src/api/routes/agent.py
I'm done. You can start.
```

---

## Cross-Domain Findings

If you discover a bug, inconsistency, or problem in another agent's domain while doing
your own work — do not fix it. Do not work around it silently. Do not leave a comment in
the file.

**Log it immediately in your worklog:**
```
🐛 CROSS-DOMAIN FINDING → [Agent name]

File: [exact path]
Problem: [what is wrong, specifically — enough detail that the owner can reproduce it]
Discovered while: [what you were doing when you found it]
Impact on my work: [how it affects the current step]
Suggested fix: [your read on the solution — the domain owner decides]
```

Then flag it to Claude. Claude decides whether to surface it to Eran immediately or
route it to the domain owner as a correction request.

---

## Disagreements

If you disagree with a decision another agent made that affects your domain — do not
silently work around it and do not revert it.

**Log it in your worklog:**
```
⚠️ DISAGREEMENT → [Agent name / decision]

What was decided: [the decision you disagree with]
Why I disagree: [specific technical or product reason]
What I propose instead: [concrete alternative]
What I need to proceed: [what needs to be resolved before I can continue]
```

Flag it to Claude. Claude escalates to Eran. **Eran's decision is final.**

---

## Worklog Protocol

Every agent maintains a worklog at `.claude/agents/logs/[name]-worklog.md`.

The worklog is written **continuously during work** — not reconstructed at the end.
The reasoning you had while making a decision is exactly what needs to be recorded.
It does not survive being reconstructed later.

**Session table format** (at the top of the file, kept current):

| Session | Date | Task | Status | Key decision |
|---|---|---|---|---|
| 001 | 2026-04-15 | Database models | ✅ Done | Used `MealIngredient` join table instead of array column |
| 002 | 2026-04-15 | Alembic migration | 🔄 WIP | — |

**Per-session sections:**
```
## Session [N] — [Task name]
**Date:** [date]
**Status:** WIP / Done

### Task brief
[What you are building and why — written immediately at start]

### Decisions
[Each decision as you make it — not reconstructed after]
- Decision: [what you chose]
  Reason: [why]
  Alternatives considered: [what you rejected]

### Issues found
[Any problem discovered mid-task — logged immediately]

### Handoff notes
[Any handoffs written at the end of this session]

### Self-review checklist
[ ] Models / schemas match what was agreed
[ ] Error cases handled and tested
[ ] Handoff notes written for affected teammates
[ ] Documentation flags written for Claude

### Documentation flags for Claude
📋
- ARCHITECTURE.md: [what changed]
- DECISIONS.md: [what was decided and why]
- GLOSSARY.md: [new term and definition]
```

**Pre-building rule — mandatory for all agents:**

If you build something during a step that belongs to a *future* protocol commit, you must log it immediately:

```
⏭️ SCOPE OVERFLOW → Commit [N] — [commit name]

What I built early: [exactly what was implemented]
Why I built it now: [the dependency or reason that made it necessary]
What Commit [N] still needs to do: [what remains — or "nothing, fully pre-built"]
```

Write this in your current session's worklog and flag it to Claude. Claude tracks it so that when Commit N arrives, its scope is known in advance — not discovered at audit time. Building ahead silently leaves the scheduled commit agent confused about what remains.

This rule applies to all agents. No exceptions.

---

## Inter-Agent Communication

All suggestions, compliments, and concerns directed at a teammate are logged in your
worklog before Claude routes them. Claude reads all worklogs and compiles inter-agent
exchanges into a summary for Eran.

**Suggestion format:**
```
💡 Suggestion → [Agent name]

What I noticed: [specific observation about their domain]
Why it matters: [the technical or product impact]
My suggestion: [concrete proposed direction]
What I'm not sure about: [your uncertainty — be honest]
I'd love your thoughts.
```

**Acknowledgement format:**
```
✨ To [Agent name]: [specific thing they built] is [specific reason it's good].
[One sentence on the impact]. Well done.
```

Only write an acknowledgement when you mean it. Hollow compliments are noise.

**Request format** (when you need something from a teammate):
```
🔧 Request → [Agent name]

What I need: [specific information or decision]
Why I need it: [the dependency — how it blocks your current step]
When I need it by: [urgency]
```

---

## Escalation Path

```
Agent notices a problem or disagreement
    └→ Logs it in their worklog (🐛 or ⚠️)
         └→ Flags it to Claude
              └→ Claude assesses urgency
                    ├→ [Blocking the current step] → Surfaces to Eran immediately
                    └→ [Not blocking] → Routes to domain owner, bundles for next check-in
                                             └→ Domain owner responds in their worklog
                                                  └→ Claude confirms resolution or re-escalates to Eran
```

Agents never resolve domain disputes directly between themselves. Claude mediates.
Eran makes the final call on anything Claude cannot resolve.

---

## Pre-Commit Checklist (Claude runs this before every commit)

```
□ ARCHITECTURE.md — does this commit introduce a new component, service, or data flow?
□ DECISIONS.md    — does this commit make a non-obvious design choice?
□ GLOSSARY.md     — does this commit introduce a new term or concept?
```

If any box is checked and the corresponding file was not updated — stop.
Update the file first, then commit.

**Credit check:**
Did this fix, finding, or decision originate from Eran?
If yes, his name MUST appear in the commit message body.

---

## Data Flow Overview

```
Customer request (natural language)
    └→ POST /agent/chat  [Nova's route]
         └→ LangGraph assistant agent  [Nova]
               ├→ search_meals(query)           → meal_service.search()  [Rex]
               ├→ check_ingredients(meal_id)    → ingredient_service.check_stock()  [Rex]
               ├→ find_substitutes(meal_id)     → meal_service.find_substitutes()  [Rex]
               └→ dispatch_order(...)           → httpx POST /orders  [Rex's route]
                                                      └→ order_service.create_order()  [Rex]
                                                           └→ Celery task enqueued  [Rex]
                                                                └→ Kitchen worker  [Rex]
                                                                     └→ PENDING → PREPARING → READY
```

**Domain boundaries in the data flow:**
- Nova owns everything above `httpx POST /orders`
- Rex owns everything from `/orders` downward
- Adam owns the infrastructure that runs all of it
- The boundary between Nova and Rex is the HTTP API — Nova calls it, Rex implements it
