"""One-use Codex production consent. The MCP server records, never executes, consent.

This is a cooperative guard, not a boundary against a process that can edit its state.
Bind consent to the session, exact tool arguments and local project snapshot. Native
tool permissions still apply after the hook has consumed a grant.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

import cmdparse
import fv
import runtime

TTL = 300


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def identity(payload):
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("Production approval requires a native session_id.")
    return {"session": session, "cwd": os.path.realpath(payload["cwd"]),
            "tool": payload["tool_name"], "input": payload.get("tool_input") or {}}


def snapshot(action):
    directories = {action["cwd"]}
    commands = []
    if action["tool"] == "Bash":
        commands = list(cmdparse.effective_commands(action["input"].get("command", ""), action["cwd"]))
        directories.update(item[2] for item in commands)
    projects = {}
    for directory in sorted(directories):
        root = fv.root_of(directory)
        if not root:
            continue
        marker = Path(root, fv.FRAMEWORK_FILE).read_bytes()
        located = subprocess.run(["git", "-C", directory, "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, timeout=5)
        if located.returncode:
            # A marker may live above the Git root. The effective command below
            # it contributes the repository; retain the outer marker as context.
            projects["marker:" + root] = hashlib.sha256(marker).hexdigest()
            continue
        repository = located.stdout.strip()
        if repository in projects:
            continue
        def git(*args):
            r = subprocess.run(["git", "-C", repository, *args], capture_output=True, timeout=15)
            if r.returncode:
                raise ValueError("Cannot snapshot the project for production approval.")
            return r.stdout
        h = hashlib.sha256(marker)
        h.update(git("rev-parse", "HEAD"))
        h.update(git("rev-parse", "--abbrev-ref", "HEAD"))
        # Hash configuration without persisting its content (remote URLs can
        # contain credentials). A changed destination requires fresh consent.
        h.update(git("config", "--null", "--list"))
        h.update(git("diff", "--binary", "HEAD", "--"))
        h.update(git("diff", "--cached", "--binary", "--"))
        for name in sorted(git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")):
            if not name:
                continue
            path = Path(repository) / os.fsdecode(name)
            h.update(name)
            if path.is_symlink():
                h.update(os.readlink(path).encode())
            elif path.is_file():
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        h.update(chunk)
        projects[repository] = h.hexdigest()
    if not any(not key.startswith("marker:") for key in projects):
        raise ValueError("Cannot find an adopted project for production approval.")
    return digest({"projects": projects, "commands": commands})


@contextlib.contextmanager
def locked():
    root = Path(runtime.state_base(), "bulletproof", "production")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def write(path, data):
    # Readers and writers hold the same lock; replace keeps partial writes invisible.
    tmp = path.with_suffix(".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        json.dump(data, stream, ensure_ascii=True)
    os.replace(tmp, path)


def read(root, request_id):
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("Invalid request ID.")
    path = root / (request_id + ".json")
    data = json.loads(path.read_text())
    if data["expires"] <= time.time():
        path.unlink()
        raise ValueError("Approval request expired. Retry the original operation to request again.")
    return path, data


def check_or_request(payload, reasons):
    action = identity(payload)
    state = snapshot(action)
    key = digest({"action": action, "snapshot": state, "reasons": reasons})
    with locked() as root:
        for path in root.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                if data["expires"] <= time.time():
                    path.unlink()
                    continue
                if data["key"] != key:
                    continue
                if data.get("approved"):
                    path.unlink()  # exactly one retry, serialized across processes
                    return True, None
                return False, path.stem
            except (ValueError, KeyError, OSError):
                continue
        request_id = secrets.token_hex(16)
        write(root / (request_id + ".json"), {
            "action": action, "snapshot": state, "key": key, "reasons": reasons,
            "expires": time.time() + TTL, "approved": False})
        return False, request_id


def pending(request_id):
    with locked() as root:
        _, data = read(root, request_id)
        if data.get("approved"):
            raise ValueError("This request has already been approved; retry the original tool once.")
        if snapshot(data["action"]) != data["snapshot"]:
            raise ValueError("Project changed. Retry the original operation for a fresh review.")
        return data


def finish(request_id, accepted):
    with locked() as root:
        path, data = read(root, request_id)
        if not accepted:
            path.unlink()
            return False
        if data.get("approved") or snapshot(data["action"]) != data["snapshot"]:
            raise ValueError("Request already approved or project changed; no new grant issued.")
        data["approved"] = True
        data["expires"] = min(data["expires"], time.time() + 120)
        write(path, data)
        return True
