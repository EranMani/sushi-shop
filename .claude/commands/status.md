Give Eran a full project status report. Be concise and scannable.

Read the following files before responding:
- `commit-protocol.md` — for the commit index and step details
- All agent worklogs in `.claude/agents/logs/` — for WIP sessions, open handoffs, and blockers

Structure your report exactly as follows:

---

## Commit Progress

Render the commit index as a table with a status column:

| # | Name | Assignee | Status |
|---|---|---|---|

Status values:
- ✅ Done — commit has been made
- 🔄 WIP — assignee's worklog shows an active session
- ⏳ Pending — not started, no blockers
- 🚫 Blocked — pending but a prerequisite handoff is missing (state what is missing)

---

## Current Step

State the active or next step clearly: who owns it, what it builds.

---

## Open Handoffs

List any handoff notes that have been written but not yet acted on.
Format: `[From] → [To]: [one sentence summary]`
If none, write: "No open handoffs."

---

## Blockers

List anything that would prevent the next step from starting.
If none, write: "No blockers."

---

## Agent Worklog Summary

For each agent with a recent worklog session, one line:
`[Agent]: [last session task] — [Done / WIP]`

---

Keep the entire report under 40 lines. Do not add commentary beyond what is asked for.
