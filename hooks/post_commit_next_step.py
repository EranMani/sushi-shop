"""Post-commit next step explanation hook.

Fires after every Bash tool call. If the command was a git commit,
injects an instruction for Claude to automatically explain what the
next protocol step will build — without the user having to ask.
"""

import json
import sys


def main() -> None:
    data = json.load(sys.stdin)
    command: str = data.get("tool_input", {}).get("command", "")

    if "git commit" not in command:
        sys.exit(0)

    message = (
        "Commit successful. "
        "You MUST now display a next-step summary to Eran in your response — every time, "
        "no exceptions, including housekeeping and documentation commits. "
        "Read commit-protocol.md to identify the next protocol step not yet committed. "
        "Then output ALL of the following in your reply:\n"
        "  1. Step number and commit message\n"
        "  2. Owner (which agent)\n"
        "  3. 2-3 sentences on what will be built and why it matters at this point\n"
        "  4. Any cross-agent coordination or prerequisite handoff needed before starting\n"
        "  5. Ask Eran: 'Shall I invoke [agent]?'\n"
        "Do not skip this. Do not summarise it into one line. Eran uses this to follow along."
    )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
