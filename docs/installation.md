# Installation and lifecycle

Version 0.4.0 supports Codex and Claude Code through the repository marketplace.
Python 3.9+, Git and Bash are required on macOS or Linux. Native acceptance was run on
macOS with Codex CLI 0.160.0. Windows is unverified.

## Codex

Install from the repository marketplace:

```bash
codex plugin marketplace add Arogus22/bulletproof
codex plugin add bulletproof@bulletproof
```

For local review before publication, run these from a checkout:

```bash
python3 scripts/package.py dist/bulletproof-0.4.0
codex plugin marketplace add ./dist/bulletproof-0.4.0
codex plugin add bulletproof@bulletproof
```

Use a fresh destination when building again. The package builder uses an allowlist,
rejects symlinks, excludes Git metadata, `.migrar-projeto`, caches and bytecode, and
creates a SHA-256 manifest. Do not register or ZIP a private working directory directly.
If the marketplace name already exists, inspect `codex plugin marketplace list` and
remove that marketplace registration before switching its source.

There are three separate checks:

1. **Package installed:** inspect `codex plugin list` and the installed version.
2. **Hooks trusted:** open `/hooks`, review the Bulletproof SessionStart and PreToolUse
   definitions and trust them. Installing/enabling alone leaves new hooks skipped.
   Review changes after updates. Never use a hook-trust bypass flag as installation.
3. **Behavior verified:** start a new session, confirm the workflows and MCP consent
   server load, and run the synthetic acceptance test described in [verification](verification.md).

In an intended project, invoke `$bulletproof:framework-init`, review its capability
questions, then `$bulletproof:testar`. The first green arms the commit guard. Projects
without the plugin marker remain unaffected. The same `.framework-version` works on
both platforms; installation and trust remain per user/host.

The Codex manifest selects `codex-skills/`, `hooks/codex.json`, and
`integrations/codex/mcp.json`. Claude retains `commands/` and `hooks/hooks.json`.
Both workflows read the same `workflows/` instructions and call the same engine.
Commands quote the installed root; hooks use a complete shell `command`, without an
unsupported separate `args` field. MCP uses an actual argv array and `cwd: "."`,
resolved by Codex relative to the plugin root. No personal paths or per-session plugin
flags are required.

## Production consent

Claude retains its native `permissionDecision: "ask"` response. Codex does not support
that response in PreToolUse: an unsupported response can fail the hook and continue
the tool. Bulletproof therefore implements a two-step consent flow on Codex:

1. A shared detector identifies a protected operation. The adapter holds it with a
   supported denial and creates an opaque pending request ID.
2. The agent calls the bundled `request_approval` MCP tool. It presents an MCP form
   containing the exact tool arguments, directory and reasons. Accepting the form
   **and** selecting its authorization checkbox grants one retry. The server does
   not execute commands and does not accept a model-supplied `approve` argument.
3. Retrying the same tool in the same session consumes the grant atomically. The
   original tool still applies Codex's sandbox, network policy and any other guards.

Requests expire after five minutes. Accepted grants last at most two minutes and
cannot outlive the request. A changed command, session, project snapshot, branch or
Git destination requires fresh consent. Cancellation, decline, timeout, unavailable
MCP or a host policy that prevents elicitation grants nothing. If another policy
blocks execution after a grant was consumed, a new attempt needs a new confirmation.
There is no auto-approval PermissionRequest hook and no execution through the MCP server.

This is a cooperative mistake-prevention mechanism, not a security boundary against
an agent or user with write access to its scripts/state. Snapshots include HEAD,
tracked/index changes, untracked non-ignored files, Git configuration, the adoption
marker and expanded command context. They do not freeze ignored files, remote data,
environment variables or external scripts. A command using those can change meaning
without a different literal input. Keep reviewable operations explicit.

Consent records temporarily contain exact arguments, which can be sensitive. Files
are created with mode 0600 in a 0700 directory. Consumed/declined requests are removed;
expired records are pruned when a later guarded operation or request accesses them.
This is not a background retention service. Do not put credentials in command lines.

## State

| Platform | Default state base |
| --- | --- |
| Claude Code | `${CLAUDE_CONFIG_DIR:-~/.claude}/state` |
| Codex | `${CODEX_HOME:-~/.codex}/state` |

The stamp is `exit-lock/<SHA-256-of-repository-path>/last-green`; the ledger is
`bulletproof/ledger.jsonl`. Codex consent requests live under `bulletproof/production/`.
The ledger records Exit Lock blocks and test outcomes, not every production consent.
`BULLETPROOF_STATE` overrides the base; `BULLETPROOF_LEDGER` overrides just the ledger.
These optional overrides are useful in tests. They are not required for installation.
State is not inside the versioned plugin cache, so updates preserve it. The platforms
do not read each other's default stamps. A failed stamp write is reported as a failure
to unlock, even when the test command succeeded.

## Update, disable and remove

For a Git marketplace, refresh the source and request the available plugin version:

```bash
codex plugin marketplace upgrade bulletproof
codex plugin add bulletproof@bulletproof
codex plugin list
```

Verify the resulting version, review changed hooks and open a new session. Local-path
marketplaces use their local source; for an unpublished replacement, build a new clean
directory, remove the old plugin/marketplace registration and register the new one.
Do not edit installed cache files. Local replacement and fresh GitHub installation were exercised; see
[verification](verification.md). An in-place remote upgrade was not tested.

Disable through the plugin UI or set `enabled = false` under
`[plugins."bulletproof@bulletproof"]` in Codex config. To uninstall:

```bash
codex plugin remove bulletproof@bulletproof
codex plugin marketplace remove bulletproof
```

Restart sessions after disabling/removing. The second command removes the catalog
registration. The project's adoption file and state outside the plugin cache remain;
removal does not delete project files or historical test records.

Claude's existing lifecycle remains:

```bash
claude plugin marketplace add Arogus22/bulletproof
claude plugin install bulletproof@bulletproof
claude plugin update bulletproof@bulletproof
claude plugin disable bulletproof@bulletproof
claude plugin uninstall bulletproof@bulletproof
```

Restart Claude after installing/updating and invoke `/bulletproof:framework-init` or
`/bulletproof:testar`. These lines describe separate lifecycle actions, not a sequence
to run all at once.

## Sources and distribution boundary

Revalidated on 2026-10-06 against the installed CLI and official documentation:
[plugin packaging](https://developers.openai.com/plugins/build/plugins),
[hook contract and trust](https://learn.chatgpt.com/docs/hooks), and
[MCP elicitation in app-server](https://learn.chatgpt.com/docs/app-server).
Repository marketplaces are the distribution route prepared here. Plugins with
lifecycle hooks are currently ineligible for the universal public plugin directory;
a working Git marketplace installation does not establish public-directory eligibility.
