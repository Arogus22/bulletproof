"""Shared production decision, with Claude's native ask response at the boundary."""
import json
import sys


class ApprovalRequired(Exception):
    pass


def ask(reason):
    raise ApprovalRequired(reason)


def claude_main(evaluate):
    try:
        data = json.load(sys.stdin)
    except (ValueError, TypeError):
        return
    try:
        evaluate(data)
    except ApprovalRequired as error:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": str(error)}}))
