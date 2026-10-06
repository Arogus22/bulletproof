#!/usr/bin/env python3
"""Small stdio MCP consent server. No shell execution or model-supplied approval flag."""
import json
import os
import sys
import threading
import uuid

os.environ["BULLETPROOF_PLATFORM"] = "codex"
import production_approval as approval

output_lock = threading.Lock()
requests_lock = threading.Lock()
waiting = {}
form_supported = False


def send(message):
    with output_lock:
        print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def result(call_id, message, error=False):
    send({"id": call_id, "result": {"content": [{"type": "text", "text": message}],
                                   "isError": error}})


def request(call_id, arguments):
    elicitation_id = "approval-" + uuid.uuid4().hex
    event = threading.Event()
    box = {}
    try:
        if not form_supported:
            raise ValueError("This client does not support MCP form elicitation; operation stays blocked.")
        if set(arguments) != {"request_id"}:
            raise ValueError("Only request_id is accepted. Consent must come from the human form.")
        request_id = arguments["request_id"]
        data = approval.pending(request_id)
        with requests_lock:
            waiting[elicitation_id] = (event, box, call_id)
        action = data["action"]
        message = ("Bulletproof production approval. Authorize ONE retry within 2 minutes?\n" +
                   "\n".join(data["reasons"]) + "\nDirectory: " + action["cwd"] +
                   "\nTool: " + action["tool"] + "\nExact arguments:\n" +
                   json.dumps(action["input"], ensure_ascii=True, indent=2) +
                   "\nThis does not grant Codex filesystem/network permissions. "
                   "Local tracked changes are checked again; external data is not frozen.")
        send({"id": elicitation_id, "method": "elicitation/create", "params": {
            "mode": "form", "message": message,
            "requestedSchema": {"type": "object", "properties": {
                "approve": {"type": "boolean", "title": "Authorize this exact operation once", "default": False}},
                "required": ["approve"]}}})
        if not event.wait(240):
            approval.finish(request_id, False)
            raise ValueError("Human confirmation timed out; no approval granted.")
        response = box.get("result") or {}
        accepted = (response.get("action") == "accept" and
                    (response.get("content") or {}).get("approve") is True)
        granted = approval.finish(request_id, accepted)
        result(call_id, "Approved once. Retry the exact original tool in the same session now."
               if granted else "Not approved. Do not retry or use another execution path.")
    except Exception as error:
        result(call_id, str(error), True)
    finally:
        with requests_lock:
            waiting.pop(elicitation_id, None)


def main():
    global form_supported
    for line in sys.stdin:
        try:
            item = json.loads(line)
            method = item.get("method")
            call_id = item.get("id")
            if not method:
                with requests_lock:
                    pending = waiting.get(call_id)
                    if pending:
                        pending[1].update(item)
                        pending[0].set()
                continue
            params = item.get("params") or {}
            if method == "initialize":
                elicitation = params.get("capabilities", {}).get("elicitation")
                form_supported = isinstance(elicitation, dict) and (not elicitation or "form" in elicitation)
                send({"id": call_id, "result": {"protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bulletproof-approval", "version": "0.4.0"}}})
            elif method == "notifications/cancelled":
                with requests_lock:
                    for event, box, original_id in waiting.values():
                        if original_id == params.get("requestId"):
                            box["result"] = {"action": "cancel"}
                            event.set()
            elif method == "ping":
                send({"id": call_id, "result": {}})
            elif method == "tools/list":
                send({"id": call_id, "result": {"tools": [{
                    "name": "request_approval",
                    "description": "Show the human a confirmation form for a pending Bulletproof production request. Never executes the operation.",
                    "inputSchema": {"type": "object", "properties": {"request_id": {"type": "string"}},
                                    "required": ["request_id"], "additionalProperties": False},
                    "annotations": {"readOnlyHint": False, "destructiveHint": False,
                                    "idempotentHint": False, "openWorldHint": False}}]}})
            elif method == "tools/call" and params.get("name") == "request_approval":
                threading.Thread(target=request, args=(call_id, params.get("arguments") or {}), daemon=True).start()
            elif call_id is not None:
                send({"id": call_id, "error": {"code": -32601, "message": "Method not found"}})
        except (ValueError, TypeError):
            send({"id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC"}})


if __name__ == "__main__":
    main()
