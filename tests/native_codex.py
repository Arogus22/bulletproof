#!/usr/bin/env python3
"""Native Codex acceptance fixture, with scripted model responses and a test client.

prepare: builds/installs into a NEW temporary CODEX_HOME, prints normal /hooks steps.
run DIR: requires those hooks already reviewed/trusted; never changes hook trust.
The client simulates consent responses only for synthetic operations. No real model,
API credentials, remote deploys, databases, or personal config are used.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid

PRODUCT = Path(__file__).resolve().parents[1]


def invoke(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def prepare(marketplace=None):
    root = Path(tempfile.mkdtemp(prefix="bulletproof-native-")).resolve()
    (root / ".bulletproof-native-verification").write_text("synthetic only\n")
    home = root / "codex-home"; home.mkdir()
    project = root / "trust-review"; project.mkdir()
    if marketplace is None:
        invoke([sys.executable, str(PRODUCT / "scripts/package.py"), str(root / "package with spaces")])
        marketplace = str(root / "package with spaces")
    env = dict(os.environ, CODEX_HOME=str(home))
    for args in (("marketplace", "add", marketplace), ("add", "bulletproof@bulletproof")):
        print(invoke(["codex", "plugin", *args], env=env))
    cfg = home / "config.toml"
    cfg.write_text('model_provider = "fixture"\nmodel = "fixture"\napproval_policy = "on-request"\n'
                   'sandbox_mode = "workspace-write"\n' + cfg.read_text() +
                   '\n[model_providers.fixture]\nname = "Synthetic acceptance fixture"\n'
                   'base_url = "http://127.0.0.1:18981/v1"\nwire_api = "responses"\nrequires_openai_auth = false\n')
    print("Review the two installed Bulletproof hooks through /hooks, then exit without a turn:")
    print("env CODEX_HOME=%s codex --no-daemon -C %s" % (shlex.quote(str(home)), shlex.quote(str(project))))
    print("Then run:")
    print("python3 tests/native_codex.py run " + shlex.quote(str(root)))


class Fixture(BaseHTTPRequestHandler):
    actions = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        item = self.actions.pop(0) if self.actions else {
            "type": "message", "id": "msg_" + uuid.uuid4().hex, "role": "assistant",
            "content": [{"type": "output_text", "text": "Synthetic case complete."}]}
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for event in (
            {"type": "response.created", "response": {"id": "fixture", "status": "in_progress", "output": []}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "fixture", "status": "completed", "output": [item],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}},
        ):
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode()); self.wfile.flush()


class Client:
    def __init__(self, root, project):
        self.log = (root / "app-server.stderr").open("w")
        self.p = subprocess.Popen(["codex", "app-server", "--stdio"], cwd=project,
            env=dict(os.environ, CODEX_HOME=str(root / "codex-home")), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.queue = queue.Queue(); self.counter = 0; self.pending = []
        def reader():
            for line in self.p.stdout:
                self.queue.put(json.loads(line))
        threading.Thread(target=reader, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "bulletproof-native-test", "version": "1"},
                                 "capabilities": {"experimentalApi": True}})
        self.send({"method": "initialized"})

    def send(self, value):
        self.p.stdin.write(json.dumps(value) + "\n"); self.p.stdin.flush()

    def call(self, method, params):
        self.counter += 1; number = self.counter
        self.send({"id": number, "method": method, "params": params})
        while True:
            message = self.queue.get(timeout=30)
            if message.get("id") == number:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]
            self.pending.append(message)

    def thread(self, project):
        return self.call("thread/start", {"cwd": str(project), "ephemeral": True,
                         "sandbox": "workspace-write", "approvalPolicy": "on-request"})["thread"]["id"]

    def turn(self, thread, name, args, consent="decline", namespace=None):
        call = "call_" + uuid.uuid4().hex
        item = {"type": "function_call", "id": "fc_" + call, "call_id": call,
                "name": name, "arguments": json.dumps(args)}
        if namespace:
            item["namespace"] = namespace
        Fixture.actions[:] = [item]
        self.call("turn/start", {"threadId": thread, "input": [{"type": "text",
                  "text": "Synthetic acceptance fixture. Execute only the supplied test action."}]})
        events = self.pending[:]; self.pending.clear()
        while True:
            message = self.queue.get(timeout=45); events.append(message)
            method = message.get("method")
            if "id" in message and method == "mcpServer/elicitation/request":
                fields = message["params"]["requestedSchema"].get("properties", {})
                self.send({"id": message["id"], "result": {"action": consent,
                    "content": ({"approve": True} if "approve" in fields else {}) if consent == "accept" else None}})
            elif "id" in message and method == "item/commandExecution/requestApproval":
                # Only the explicit synthetic command submitted by this client.
                self.send({"id": message["id"], "result": {"decision": "accept"}})
            elif "id" in message and method:
                raise RuntimeError("Unexpected native approval: " + method)
            if method == "turn/completed":
                return events

    def close(self):
        self.p.terminate(); self.p.wait(timeout=10); self.log.close()


def repo(root, name, adopted=True):
    project = root / name; project.mkdir()
    (project / ".gitignore").write_text("__pycache__/\n*.sentinel\n")
    (project / "app.py").write_text("value = 1\n")
    (project / "test_app.py").write_text("import unittest\nfrom app import value\nclass Test(unittest.TestCase):\n def test_positive(self): self.assertGreater(value, 0)\n")
    # This executable only records a local canary. It cannot access D1 or the network.
    (project / "wrangler").write_text("#!/bin/sh\nprintf 'synthetic only\\n' >> d1.sentinel\n")
    (project / "wrangler").chmod(0o700)
    if adopted:
        (project / ".framework-version").write_text(json.dumps({"plugin": "bulletproof", "version": "0.3",
            "status": "active", "layers": [1, 2, 3], "stacks": ["python"],
            "tests": {"python": "python3 -m unittest -q"}, "config": {
                "deploy": {"protected_branch": "main", "deploy_cmds": ["wrangler deploy"]},
                "prod_db": {"kind": "d1"}}}))
    for args in (("init", "-q", "-b", "main"), ("config", "user.name", "Synthetic"),
                 ("config", "user.email", "synthetic@example.invalid"), ("add", "."), ("commit", "-qm", "baseline")):
        invoke(["git", *args], cwd=project)
    (project / "app.py").write_text("value = 2\n")
    return project


def hooks(events, status=None):
    return [e["params"]["run"] for e in events if e.get("method") == "hook/completed"
            and (status is None or e["params"]["run"]["status"] == status)]


def request_id(events):
    return re.search(r"request_id=([a-f0-9]{32})", json.dumps(events)).group(1)


def executed(events):
    return any(e.get("method") == "item/completed" and e["params"]["item"]["type"] == "commandExecution"
               and e["params"]["item"].get("exitCode") == 0 for e in events)


def fake_d1(root):
    """Native MCP canary: records a synthetic write locally, without D1 access."""
    if not (root / ".bulletproof-native-verification").is_file():
        raise ValueError("Synthetic test directory required")
    for line in sys.stdin:
        item = json.loads(line); method = item.get("method")
        if "id" not in item:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "synthetic-d1", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "d1_query", "description": "Synthetic local canary only.",
                      "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}]}
        elif method == "tools/call":
            if "DELETE" in item["params"]["arguments"]["sql"]:
                with (root / "mcp.sentinel").open("a") as stream:
                    stream.write("synthetic only\n")
            result = {"content": [{"type": "text", "text": "Synthetic D1 query complete."}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": item["id"], "result": result}), flush=True)


def run(root):
    root = root.resolve()
    if not (root / ".bulletproof-native-verification").is_file() or Path(tempfile.gettempdir()).resolve() not in root.parents:
        raise ValueError("Run only in the temporary directory created by prepare.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    config = root / "codex-home/config.toml"
    config.write_text(re.sub(r"http://127\.0\.0\.1:\d+/v1", "http://127.0.0.1:%d/v1" % server.server_port, config.read_text()))
    if "[mcp_servers.synthetic_d1]" not in config.read_text():
        with config.open("a") as stream:
            stream.write('\n[mcp_servers.synthetic_d1]\ncommand = ' + json.dumps(sys.executable) +
                         '\nargs = ' + json.dumps([str(Path(__file__).resolve()), "fake-d1", str(root)]) + '\n')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    run_id = uuid.uuid4().hex[:8]
    project = repo(root, "adopted " + run_id)
    plain = repo(root, "unadopted " + run_id, False)
    client = Client(root, project); evidence = []; passed = []
    def check(name, condition, events=None):
        evidence.append({"case": name, "passed": bool(condition), "events": events or []})
        print(("PASS " if condition else "FAIL ") + name, flush=True)
        assert condition, name
        passed.append(name)
    try:
        listed = client.call("hooks/list", {"cwds": [str(project)]})["data"][0]
        entries = [h for h in listed["hooks"] if h.get("pluginId") == "bulletproof@bulletproof"]
        check("two trusted plugin hooks", len(entries) == 2 and all(h["trustStatus"] == "trusted" for h in entries))
        skills = client.call("skills/list", {"cwds": [str(project)], "forceReload": True})["data"][0]["skills"]
        check("both workflows discovered", {s["name"] for s in skills if s.get("pluginId") == "bulletproof@bulletproof"} == {"bulletproof:framework-init", "bulletproof:testar"})
        thread = client.thread(project)
        def shell(command, target=project, tid=thread, escalate=False):
            args = {"cmd": command, "workdir": str(target), "max_output_tokens": 2000}
            if escalate:
                args.update(sandbox_permissions="require_escalated", justification="Synthetic verification in temporary repositories only.")
            return client.turn(tid, "exec_command", args)
        head = invoke(["git", "rev-parse", "HEAD"], project)
        events = shell("git add -A && git commit -m verified")
        check("fresh SessionStart executes", any(h["eventName"] == "sessionStart" and h["status"] == "completed" and h["entries"] for h in hooks(events)), events)
        check("commit blocked without green", bool(hooks(events, "blocked")) and invoke(["git", "rev-parse", "HEAD"], project) == head, events)
        cache = root / "codex-home/plugins/cache/bulletproof/bulletproof/0.4.0"
        adoption = root / ("adoption " + run_id)
        adoption.mkdir()
        invoke(["git", "init", "-q", str(adoption)])
        events = shell("python3 %s --platform codex framework-init . --stack python" %
                       shlex.quote(str(cache / "scripts/run.py")), adoption)
        marker = json.loads((adoption / ".framework-version").read_text())
        check("installed framework-init adopts a new project", executed(events) and
              marker.get("plugin") == "bulletproof" and marker.get("status") == "bootstrapping", events)
        events = shell("python3 %s --platform codex testar ." % shlex.quote(str(cache / "scripts/run.py")))
        check("shared runner tests and stamps", executed(events) and "testar: GREEN" in json.dumps(events), events)
        events = shell("git add -A && git commit -m verified", escalate=True)
        check("green releases real commit", executed(events) and invoke(["git", "rev-parse", "HEAD"], project) != head, events)
        (project / "app.py").write_text("value = 3\n")
        head = invoke(["git", "rev-parse", "HEAD"], project)
        events = shell("git add -A && git commit -m changed")
        check("new change invalidates green", bool(hooks(events, "blocked")) and invoke(["git", "rev-parse", "HEAD"], project) == head, events)
        remote = root / ("remote " + run_id + ".git")
        invoke(["git", "init", "--bare", "-q", str(remote)])
        invoke(["git", "remote", "add", "synthetic", str(remote)], project)
        command = "git push synthetic main"
        events = shell(command); rid = request_id(events)
        check("production push held", bool(hooks(events, "blocked")) and not (remote / "refs/heads/main").exists(), events)
        for answer in ("decline", "cancel", "accept"):
            events = client.turn(thread, "request_approval", {"request_id": rid}, answer, "mcp__approval")
            check("native consent " + answer, any(e.get("method") == "mcpServer/elicitation/request" for e in events), events)
            events = shell(command, escalate=answer == "accept")
            if answer != "accept":
                check("still blocked after " + answer, bool(hooks(events, "blocked")) and not (remote / "refs/heads/main").exists(), events)
                rid = request_id(events)
            else:
                check("consent releases only original tool", executed(events) and (remote / "refs/heads/main").exists(), events)
        check("consent consumed once", bool(hooks(shell(command), "blocked")))
        command = './wrangler d1 execute synthetic --remote --command "DELETE FROM demo"'
        events = shell(command); rid = request_id(events)
        check("D1 write held before executable", bool(hooks(events, "blocked")) and not (project / "d1.sentinel").exists(), events)
        events = client.turn(thread, "request_approval", {"request_id": rid}, "accept", "mcp__approval")
        check("native D1 consent", any(e.get("method") == "mcpServer/elicitation/request" for e in events), events)
        events = shell(command)
        check("D1 synthetic executable released", executed(events) and (project / "d1.sentinel").read_text() == "synthetic only\n", events)
        events = shell(command)
        check("D1 retry blocked", bool(hooks(events, "blocked")) and (project / "d1.sentinel").read_text() == "synthetic only\n", events)
        before = (root / "mcp.sentinel").read_text() if (root / "mcp.sentinel").exists() else ""
        events = client.turn(thread, "d1_query", {"sql": "DELETE FROM demo"}, namespace="mcp__synthetic_d1")
        rid = request_id(events)
        check("native MCP D1 write held", bool(hooks(events, "blocked")), events)
        consent_events = client.turn(thread, "request_approval", {"request_id": rid}, "accept", "mcp__approval")
        evidence.append({"case": "MCP consent response", "events": consent_events})
        events = client.turn(thread, "d1_query", {"sql": "DELETE FROM demo"}, namespace="mcp__synthetic_d1")
        check("native MCP permissions still apply", "user rejected MCP tool call" in json.dumps(events) and not hooks(events, "blocked"), events)
        events = client.turn(thread, "d1_query", {"sql": "DELETE FROM demo"}, namespace="mcp__synthetic_d1")
        check("host rejection consumes the one-use grant", bool(hooks(events, "blocked")), events)
        rid = request_id(events)
        client.turn(thread, "request_approval", {"request_id": rid}, "accept", "mcp__approval")
        events = client.turn(thread, "d1_query", {"sql": "DELETE FROM demo"}, "accept", "mcp__synthetic_d1")
        check("native MCP D1 consent releases once", not hooks(events, "blocked") and (root / "mcp.sentinel").exists() and (root / "mcp.sentinel").read_text() == before + "synthetic only\n", events)
        events = client.turn(thread, "d1_query", {"sql": "SELECT * FROM demo"}, "accept", "mcp__synthetic_d1")
        read_completed = any(e.get("method") == "item/completed" and e["params"]["item"].get("type") == "mcpToolCall" and e["params"]["item"].get("status") == "completed" for e in events)
        check("native MCP D1 read passes", read_completed and not hooks(events, "blocked") and (root / "mcp.sentinel").read_text() == before + "synthetic only\n", events)
        tid = client.thread(plain)
        events = shell("git add -A && git commit -m unmanaged", plain, tid, True)
        check("unadopted project unaffected", executed(events) and not hooks(events, "blocked") and all(not h["entries"] for h in hooks(events)), events)
        key = hashlib.sha256(str(project).encode()).hexdigest()
        check("Codex state stored under isolated home", (root / "codex-home/state/exit-lock" / key / "last-green").is_file())
    finally:
        (root / "native-results.json").write_text(json.dumps(evidence, indent=2) + "\n")
        client.close(); server.shutdown(); server.server_close()
    print("%d native acceptance checks passed. Consent responses were simulated by the test client." % len(passed))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "fake-d1"))
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--marketplace", help="Install from this marketplace source instead of a local package (prepare only).")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.marketplace)
    elif args.action == "fake-d1" and args.directory:
        fake_d1(args.directory)
    elif args.directory:
        run(args.directory)
    else:
        parser.error("run requires the directory returned by prepare")
