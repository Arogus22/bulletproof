#!/usr/bin/env python3
"""ledger.py -- record of Bulletproof interventions (append-only, JSONL).

GENERIC base piece: any hook/gate can call it to record when it stopped or caught
something, so that later you can audit "how many times it saved us". Global (a single
file, with a `project` field to filter by project), in
~/.claude/state/bulletproof/ledger.jsonl: an absolute path, it survives plugin
updates. Best-effort: it NEVER raises (the caller cannot break because of this).

Two uses:
  module:  import ledger; ledger.record(event="block", gate="exit_lock", project=..., ...)
  CLI:     python3 ledger.py <event> <gate> <project> [--reason R] [--session S] \
                    [--incident-seed X] [--detail JSON]

Expected events: "block" (a gate stopped an action), "test_red" (a test caught a real
failure), "test_green" (the tests passed; it serves as the denominator). The `event`
field labels them so that the report never adds blocks together with bugs caught.

Env overrides (for tests, they never touch the real state):
  BULLETPROOF_LEDGER: the path of the ledger file.
"""
import datetime
import hashlib
import json
import os
import runtime


def _ledger_path():
    return os.environ.get("BULLETPROOF_LEDGER") or \
        os.path.join(runtime.state_base(), "bulletproof", "ledger.jsonl")


def _incident(project, seed):
    """Stable hash to group retries of the same incident (e.g. 3 attempts to commit
    the same non-green code = 1 incident). seed = the fingerprint when there is one."""
    base = "%s|%s" % (project or "", seed or "")
    return hashlib.sha256(base.encode()).hexdigest()[:12]


def record(event, gate, project, reason=None, incident_seed=None,
           session=None, detail=None):
    """Appends one line to the ledger. Best-effort, it never raises; returns a bool."""
    try:
        rec = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event,
            "gate": gate,
            "project": project,
            "incident": _incident(project, incident_seed),
        }
        if reason is not None:
            rec["reason"] = reason
        if session is not None:
            rec["session"] = session
        if detail is not None:
            rec["detail"] = detail
        path = _ledger_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # appending a line < 4KB is atomic on POSIX: several Claude sessions writing
        # at the same time do not corrupt the file.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _main(argv):
    import argparse
    p = argparse.ArgumentParser(description="append one intervention to the ledger")
    p.add_argument("event")
    p.add_argument("gate")
    p.add_argument("project")
    p.add_argument("--reason")
    p.add_argument("--session")
    p.add_argument("--incident-seed", dest="incident_seed")
    p.add_argument("--detail", help="JSON with extra detail")
    a = p.parse_args(argv)
    detail = None
    if a.detail:
        try:
            detail = json.loads(a.detail)
        except Exception:
            detail = {"raw": a.detail}
    ok = record(event=a.event, gate=a.gate, project=a.project, reason=a.reason,
                incident_seed=a.incident_seed, session=a.session, detail=detail)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
