"""Pre-commit markdown checklist hook.

Fires before every Bash tool call. If the command is a git commit,
injects a checklist reminder into Claude's context — forcing a check
that all relevant markdown files were updated before the commit lands.
"""

import json
import sys


def main() -> None:
    data = json.load(sys.stdin)
    command: str = data.get("tool_input", {}).get("command", "")

    if "git commit" not in command:
        sys.exit(0)

    checklist = (
        "PRE-COMMIT MARKDOWN CHECK — confirm before committing:\n"
        "  □ ARCHITECTURE.md      — new component, data flow, or system boundary introduced?\n"
        "  □ DECISIONS.md         — non-obvious design or technical choice made this step?\n"
        "  □ GLOSSARY.md          — new concept or term introduced?\n"
        "  □ TASKS.md             — any out-of-protocol work items discovered?\n"
        "  □ learning_concepts.md — did this step introduce a concept worth explaining to Eran?\n"
        "                           Only add an entry if the concept is non-obvious or interesting.\n"
        "                           Wiring and boilerplate steps can skip this. 1–2 concepts max.\n"
        "If any box applies and the file was not updated, stop and update it first.\n"
        "\n"
        "HANDOFF CHECK — does this commit produce output another agent depends on?\n"
        "  □ If yes, a handoff note is written at the bottom of the committing agent's worklog.\n"
        "  □ Handoff note includes: what was built, key decisions, data shapes, files to read,\n"
        "    and ends with 'I'm done. You can start.'\n"
        "  □ Claude will route the handoff to the receiving agent before invoking them.\n"
        "\n"
        "CROSS-DOMAIN FINDINGS CHECK:\n"
        "  □ Any bugs or issues found outside this agent's domain are logged with 🐛 CROSS-DOMAIN FINDING\n"
        "    in the worklog — NOT fixed silently. Claude routes the fix.\n"
        "\n"
        "ERAN CREDIT CHECK — did this fix, finding, or decision originate from Eran?\n"
        "  □ If yes, his name MUST appear in the commit message body\n"
        "    (e.g. 'Eran identified...', 'raised by Eran during review...', 'Eran required...')\n"
        "  □ If no, no credit line needed.\n"
        "\n"
        "AGENT IDENTITY CHECK — is this commit assigned to Aria, Rex, Nova, or Claude?\n"
        "  □ Aria commits must include: Co-Authored-By: Aria <aria.stockagent@gmail.com>\n"
        "  □ Rex commits must include:  Co-Authored-By: Rex <rex.stockagent@gmail.com>\n"
        "  □ Nova commits must include: Co-Authored-By: Nova <nova.nodegraph@gmail.com>\n"
        "  □ Claude commits must include: Co-Authored-By: Claude <claude@anthropic.com>\n"
        "  □ Only files within the committing agent's domain are staged.\n"
    )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": checklist,
        }
    }))


if __name__ == "__main__":
    main()
