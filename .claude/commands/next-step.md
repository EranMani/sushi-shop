Read `commit-protocol.md` and identify the first commit whose status is `pending`.

Then do the following in order:

1. **Identify the step** — state the commit number, name, and assignee clearly.

2. **Check prerequisites** — read the worklog of the assignee (`.claude/agents/logs/[name]-worklog.md`) and the worklogs of any teammates whose output this step depends on (see `AGENTS.md` dependency map). Report whether all required handoff notes are in place. If any are missing, stop here and tell Eran what is blocking the step.

3. **Brief Eran** — in 3–5 bullet points, explain what this step will build, why it comes at this point in the sequence, and what it unlocks for the steps that follow.

4. **Ask for approval** — end with exactly this:

> Ready to begin **[commit name]** (assigned to [Agent]).
> Shall I proceed?

Do not start any work until Eran confirms.
