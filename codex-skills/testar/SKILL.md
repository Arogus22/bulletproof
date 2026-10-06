---
name: testar
description: Check coverage of current changes, run the adopted project test suites and stamp a successful run. Use when asked to run Bulletproof tests; this is not a report-only whole-project audit.
---

Read and follow [the shared workflow](../../workflows/testar.md).

Resolve the plugin root as two directories above this SKILL.md, using its actual
absolute path from the skill listing. Run the following with that resolved path:

```bash
python3 "<plugin-root>/scripts/run.py" --platform codex testar .
```

Pass any requested workflow arguments. In shared text, `/bulletproof:framework-init`
means `$bulletproof:framework-init` and `/bulletproof:testar` means `$bulletproof:testar` on Codex.
For production blocks, call the bundled `request_approval` MCP tool with the request
ID. Only its human confirmation form grants one retry. Decline, cancellation or
missing MCP support leaves the operation blocked; never write an approval file.
