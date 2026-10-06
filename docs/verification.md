# Verification of 0.4.0

Run on 2026-10-06, macOS, Python 3.14.2. The starting repository was v0.3.0,
`ebb7c144cc94e9aa71ea70ea3dc85fe8c9108891`, with 35 commits and no tracked changes.
The initial checks below preceded publication. Remote installation is a separate
acceptance step; a successful local package test alone does not prove it.

## Automated suites

- Original ten suites: **290/290 checks pass**, repeated before and after the change.
- Codex adapter/consent suite: **19 unittest cases pass**. Covers platform state,
  green/invalidation, no adoption, no session identity, one-use consent, decline,
  expiration, concurrent retry, different session/command, changed content/remote,
  adoption marker above Git, combined deploy+D1, MCP D1, invalid request IDs, stamp
  write failure and rejection of a model-supplied consent flag.
- Package integrity: **1 unittest case passes**, including hashes, both host layouts,
  excluded private metadata and refusal to overwrite an existing package.
- JSON manifests parse; Python scripts parse with Python 3.9 grammar. Both Codex
  skills pass the skill validator. Native Claude marketplace validation passes.

Python 3.9 grammar validation is not a Python 3.9 runtime test. The CI matrix is
updated but has not run on these unpublished changes. Linux and other Python
versions retain the CI definition; they were not rerun locally in this task.

## Native Codex: 26 acceptance checks pass

Codex CLI/app-server 0.160.0 installed the clean package through normal
`plugin marketplace add` and `plugin add` commands in a temporary `CODEX_HOME`.
`hooks/list` first reported two untrusted hooks. They were reviewed and trusted through
the normal CLI interface. No trust hashes were forged and no bypass flag was used.

The real runtime then loaded the package in fresh sessions, dispatched the hooks and
controlled the original tools. A local Responses fixture supplied deterministic tool
calls; it did not emulate hook execution. The app-server client simulated acceptance,
decline and cancellation at the normal consent interfaces.

Verified behavior includes:

- Discovery of both namespaced workflows, installed paths and two trusted hooks.
- Successful SessionStart execution and model-visible project guidance.
- A blocked commit leaves HEAD unchanged; a real test run stamps green and permits
  a real local commit; a later source edit is blocked again.
- Protected-branch push held before a local bare remote changes; decline and cancel
  preserve the block; acceptance permits one exact retry; reuse blocks again.
- D1 CLI write held before a synthetic executable runs, then released once after
  consent. The executable only appends a local canary; no Cloudflare access occurs.
- D1 through a real stdio MCP canary: write blocked, then one approved retry executes;
  a read passes. Codex's independent MCP tool approval can still reject a call after
  Bulletproof consent. The consumed grant does not bypass that rejection.
- Unadopted project: hooks produce no intervention and a local commit succeeds.
- State is written under the isolated Codex profile. Executable package files and
  workflow contents were compared byte-for-byte with the working source.

## Native Claude regression: 5 scenarios pass

The CLI launcher reports 2.1.283; the isolated SDK session's own `init` event identifies
its executing runtime as **2.1.79**. Attribute the following proof to that session
runtime, rather than assuming the launcher and worker version are interchangeable.

Normal marketplace installation into temporary `CLAUDE_CONFIG_DIR`, discovery of
both commands, and real SessionStart output were observed. Five native scenarios pass:
commit block without green, test/green/commit, invalidation, production refusal, and
production acceptance. The native debug log explicitly records the production guard's
`permissionDecision: ask`; the normal `can_use_tool` host callback mediates the decision.

The fixture uses Claude print/SDK mode in a newly created synthetic workspace, with a
local scripted Anthropic endpoint and a synthetic token. It does not use a real model
or real API credentials. It does not pass permission or hook bypass flags. SDK-mode
workspace trust is not evidence of an interactive Claude trust-dialog test.

## Reproduce

Run isolated script tests:

```bash
failed=0
for test in tests/test_*.py; do python3 "$test" || failed=1; done
exit "$failed"
```

For Codex, prepare a new temporary profile:

```bash
python3 tests/native_codex.py prepare
```

Follow the printed CLI command to review the installed hooks through `/hooks`, exit,
then run the printed `run` command. The runner refuses an unprepared directory or
untrusted hooks. It binds only to loopback, creates fresh synthetic repositories per
run and saves `native-results.json`. It needs permission to run local subprocesses and
open its loopback fixture. Use the normal host permission mechanism if restricted.

To test the repository marketplace in a new isolated profile, use:

```bash
python3 tests/native_codex.py prepare --marketplace Arogus22/bulletproof
```

Follow the same hook review and run steps. This also exercises the installed
`framework-init` and `testar` entry points in synthetic repositories.

For Claude:

```bash
python3 tests/native_claude.py
```

This also installs only in a new temporary profile and prints its evidence directory.
Native fixtures are opt-in and are not part of the ordinary Python CI loop. Temporary
profiles and evidence are retained for review; no personal profile is installed into.

## Limits

These are real host/runtime tests with synthetic model responses, consent clients,
Git destinations and D1 tools. They do not evaluate autonomous model skill-following,
the desktop application's visual consent UI, real Cloudflare operations, every shell
spelling, or future runtime versions. Claude interactive 2.1.283 is not covered by the
SDK worker's 2.1.79 proof. Remote installation/update of 0.4.0 remains untested until
publication; local package installation, removal and replacement were exercised.

Payload tests are reported separately from native proof. Runtime hook timeouts,
unexpected host errors, command coverage limits and editable local state remain
limitations; Bulletproof is not an adversarial security boundary. No whole-project
report-only audit or downstream application comparison was executed.
