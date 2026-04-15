# claude_workflow.md — Sushi Shop

> A record of every Claude Code configuration decision made for this project.
> Documents what was added, what was deliberately skipped, and why.
> Updated whenever a hook, command, or Claude Code behaviour is changed.

---

## Hooks

Hooks are shell commands that Claude Code executes automatically in response to tool
events. They inject context into Claude's conversation or block/allow actions.
Configured in `.claude/settings.json`.

---

### PreToolUse — `hooks/pre_commit_check.py`

**Trigger:** Any `Bash` tool call containing `git commit`

**What it does:**
Injects a structured checklist into Claude's context before every commit. Forces Claude
to confirm that all relevant markdown files were updated before the commit lands.

**Checklist sections:**
1. **Markdown check** — did this step introduce anything that should update `ARCHITECTURE.md`,
   `DECISIONS.md`, `GLOSSARY.md`, `TASKS.md`, or `learning_concepts.md`?
2. **Handoff check** — does this commit produce output another agent depends on? If yes,
   a handoff note must be written in the committing agent's worklog.
3. **Cross-domain findings check** — any bugs or issues found outside the agent's domain
   must be logged with `🐛 CROSS-DOMAIN FINDING` in the worklog, not fixed silently.
4. **Eran credit check** — if the fix, finding, or decision originated from Eran, his name
   must appear in the commit message body.
5. **Agent identity check** — confirms the correct `Co-Authored-By` email is used and only
   files within the committing agent's domain are staged.

**Why this hook, not a prose rule:**
CLAUDE.md already lists these as requirements. The hook makes Claude re-read them at exactly
the right moment — when a commit command is detected — so nothing slips through because
the checklist was buried in a long document.

---

### PostToolUse — `hooks/post_commit_next_step.py`

**Trigger:** Any `Bash` tool call containing `git commit`

**What it does:**
After a successful commit, injects an instruction forcing Claude to immediately read
`commit-protocol.md`, identify the next pending step, and present a structured summary
to Eran — without Eran having to ask.

**Summary format Claude must produce:**
1. Step number and commit message
2. Owner (which agent)
3. 2–3 sentences on what will be built and why it matters at this point
4. Any cross-agent coordination or prerequisite handoff needed
5. "Shall I invoke [agent]?"

**Why this matters:**
Every commit hands off to the next step. Without this hook, Eran would have to ask
"what's next?" after every commit. The hook makes the handoff automatic and consistent.

---

### Hooks considered and skipped

| Hook | Why skipped |
|---|---|
| **Stop hook — worklog reminders** | Fires at session end, not commit time. Worklogs are already updated as part of each commit step. The memory system handles cross-session context. |
| **PreToolUse on Write/Edit — domain guard** | The hook can't know which agent is currently active (no `CURRENT_AGENT` in the shell). False positives would block legitimate cross-domain reads by Claude. The pre-commit AGENT IDENTITY CHECK is the correct enforcement point. |
| **UserPromptSubmit — protocol injection** | Fires on every prompt, not just session starts. The memory system already handles session re-orientation. The `/project:next-step` and `/project:status` commands cover on-demand state checks. |

---

## Custom Slash Commands

Custom slash commands live in `.claude/commands/`. Each is a markdown file whose contents
are injected as a prompt when the command is invoked. Invoked as `/project:<name>` in Claude Code.

---

### `/project:next-step`

**File:** `.claude/commands/next-step.md`

**What it does:**
Reads `commit-protocol.md`, identifies the first pending step, checks all prerequisite
handoffs, briefs Eran on what the step builds and why it comes at this point in the
sequence, then asks for approval before any work begins.

**When to use:** After a commit, or when returning to the project and wanting a precise
answer to "what do we do next?"

---

### `/project:status`

**File:** `.claude/commands/status.md`

**What it does:**
Produces a full project status report: commit progress table (✅ Done / 🔄 WIP / ⏳ Pending /
🚫 Blocked), current step, open handoffs, blockers, and a one-line worklog summary per agent.
Capped at 40 lines to stay scannable.

**When to use:** At the start of a session, or any time you want a bird's-eye view of
where the project stands.

---

### `/project:handoff-check`

**File:** `.claude/commands/handoff-check.md`

**What it does:**
Targeted check on the next pending step only. Reads the dependency map in `AGENTS.md`,
checks whether all required handoff notes exist in the relevant worklogs, and gives a
clear verdict: ✅ Clear to start / ⚠️ Partially ready / 🚫 Blocked.

**When to use:** Before invoking an agent for a step that depends on another agent's output.
Faster than `/project:status` when you only want a go/no-go on the next step.

---

## Things considered and skipped

| Item | Why skipped |
|---|---|
| **MCP — Postgres** | Rex writes SQLAlchemy models and migrations; he doesn't need a live DB connection. Would require docker-compose running during all development. |
| **MCP — GitHub** | No issue tracker workflow, no PR review process. Commits go to `main` through the protocol with Eran's approval. Nothing for agents to read from or write to GitHub beyond `git` commands. |
| **MCP — Memory** | The file-based memory system at `~/.claude/projects/...` already handles cross-session context and was proven to work on the first session. A second memory store would duplicate and drift. |
| **inputSchema on agent files** | Agent files are persona documents, not API specs. A schema in a markdown file is advisory prose — nothing validates it. The context model is already defined in `AGENTS.md` and the commit protocol. |

---

## Memory System

Claude Code's auto-memory persists context across sessions at:
`C:\Users\eranm\.claude\projects\D--AI--My-Projects-sushi-shop\memory\`

Files:
- `MEMORY.md` — index (loaded into every session automatically)
- `user_profile.md` — Eran's role, working style, preferences
- `project_state.md` — what's built, what's next, where we left off
- `feedback_workflow.md` — how Eran likes to work through issues

**Why file-based memory over a Memory MCP:** Already working, no extra server to configure,
no second context store to drift from the project state.

---

## Settings

**File:** `.claude/settings.json`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "python hooks/pre_commit_check.py" }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "python hooks/post_commit_next_step.py" }]
      }
    ]
  }
}
```
