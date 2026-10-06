---
description: Runs the project's test layer (Bulletproof), with a coverage self-check first (Step 0). Green stamps and unlocks the commit; red records the failure and keeps the Exit Lock on.
allowed-tools: Bash(python3 *) Bash(git *) Read Grep Glob Edit Write
---

Read and follow `${CLAUDE_PLUGIN_ROOT}/workflows/testar.md`.

For its script step, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" --platform claude testar .
```

Preserve any user-supplied arguments from `$ARGUMENTS`.
