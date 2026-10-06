#!/usr/bin/env python3
"""Codex adapter: shared guards, supported output, MCP-mediated human consent."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ["BULLETPROOF_PLATFORM"] = "codex"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from approval_policy import ApprovalRequired
import production_approval


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": reason}}))


def main():
    payload = json.load(sys.stdin)
    event = payload.get("hook_event_name")
    if event == "SessionStart":
        guide = load("framework-guide")
        data = guide.gate.managed_project(payload.get("cwd") or os.getcwd())
        if data is not None:
            context = guide.message(data, guide.gate.root_of(payload["cwd"]))
            context = context.replace("/bulletproof:testar", "$bulletproof:testar").replace(
                "/bulletproof:framework-init", "$bulletproof:framework-init")
            context += (" In Codex, a production block provides a request ID. Call the "
                        "Bulletproof request_approval MCP tool with that ID to show the human "
                        "confirmation form. Retry the exact original tool once only after "
                        "acceptance. Never edit grants or use an alternative execution path.")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                              "additionalContext": "[Bulletproof] " + context}}))
        return
    if event != "PreToolUse":
        return
    tool = payload.get("tool_name", "")
    if tool == "Bash":
        result = subprocess.run([sys.executable, str(HERE / "exit-lock-guard.py")],
                                input=json.dumps(payload), capture_output=True, text=True)
        if result.returncode == 2:
            deny(result.stderr)
            return
    reasons = []
    for name in ("deploy-guard", "db-guard"):
        try:
            load(name).evaluate(payload)
        except ApprovalRequired as error:
            reasons.append(str(error))
    if not reasons:
        return
    try:
        allowed, request_id = production_approval.check_or_request(payload, reasons)
    except Exception as error:
        deny("Bulletproof production approval unavailable: %s. Operation remains blocked." % error)
        return
    if not allowed:
        deny(" ".join(reasons) + " Call Bulletproof request_approval with request_id=" +
             request_id + ". The human must accept its confirmation form. Then retry this "
             "exact tool call once in this session. Decline/cancel/expiry grants nothing.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Codex continues after hook errors, so emit an explicit supported denial.
        deny("Bulletproof could not evaluate the operation: %s" % error)
