"""Platform boundary: state paths and workflow names. No machine-specific paths."""
import os
import sys


def platform():
    return os.environ.get("BULLETPROOF_PLATFORM", "claude")


def state_base():
    override = os.environ.get("BULLETPROOF_STATE")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if platform() == "codex":
        home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    else:
        home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(home, "state")


def workflow(name):
    return "$bulletproof:%s" % name if platform() == "codex" else "/bulletproof:%s" % name


if __name__ == "__main__":
    if sys.argv[1:] == ["state"]:
        print(state_base())
