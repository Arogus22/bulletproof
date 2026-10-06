---
description: "Adopts the current project into Bulletproof: detects the capabilities (database, deploy), proposes the layers and writes the control file. Asks you to confirm what it cannot see."
argument-hint: "[optional stacks, e.g. python node]"
disable-model-invocation: true
allowed-tools: Bash(python3 *) Read Edit
---

Read and follow `${CLAUDE_PLUGIN_ROOT}/workflows/framework-init.md`.

For its script step, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" --platform claude framework-init .
```

Preserve any user-supplied arguments from `$ARGUMENTS`.
