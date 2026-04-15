Check whether the next pending commit step has everything it needs to start.

Read the following files:
- `commit-protocol.md` — identify the first pending step, its assignee, and what it builds
- `AGENTS.md` — check the dependency map for this step (whose worklog must be read first)
- All relevant agent worklogs in `.claude/agents/logs/`

Then report the following:

---

## Handoff Check — [Commit Name]

**Assignee:** [Agent name]
**Depends on:** [list of agents whose output this step consumes, or "None"]

---

## Required Handoffs

For each dependency, check whether a handoff note exists in the relevant worklog:

| From | To | Status | Summary |
|---|---|---|---|
| [Agent] | [Agent] | ✅ Present / ❌ Missing | [one sentence of what the handoff covers, or "—"] |

---

## Verdict

Choose one:

**✅ Clear to start** — all required handoffs are present. [Agent] can begin immediately.

**⚠️ Partially ready** — [list what is present and what is missing]. The step can start but [Agent] should be aware of the missing context.

**🚫 Blocked** — required handoff from [Agent] is missing. The step cannot start until [Agent] completes their handoff note. Recommend surfacing this to Eran.

---

## Recommended Action

One sentence telling Eran exactly what to do next.
