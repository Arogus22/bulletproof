# Bulletproof

Test discipline for Claude Code, enforced by hooks instead of by the model's goodwill.

[![tests](https://github.com/Arogus22/bulletproof/actions/workflows/tests.yml/badge.svg)](https://github.com/Arogus22/bulletproof/actions/workflows/tests.yml)

## The problem

A coding agent says "done" without proof, and commits code that does not work. You can write "always run the tests before committing" in `CLAUDE.md`, and it will be followed most of the time. Most of the time is the problem: an instruction is a suggestion to the model, and under a long task or a tight context it gets skipped.

A hook is not a suggestion. It runs outside the model, every time, and the model cannot talk its way past it. Bulletproof turns three rules into hooks:

1. **Code is only committed after a green test run of that exact code.** Not "tests passed earlier today": the code being committed has to be the code that was tested.
2. **The agent is told the rules of the project when the session starts**, so it works with them instead of discovering them by being blocked.
3. **Anything that reaches production stops and asks you first.** A deploy, a push to the production branch, a write to the production database.

It does nothing at all in a project until you adopt that project. See [What it does not do](#what-it-does-not-do).

## Install

In Claude Code:

```
/plugin marketplace add Arogus22/bulletproof
```

```
/plugin install bulletproof@bulletproof
```

The name appears twice on purpose: it is `plugin@marketplace`, and both are called `bulletproof`.

Then **restart Claude Code**. Hooks are registered when a session starts, so the plugin is not active in the session that installed it.

The same two steps from a terminal:

```bash
claude plugin marketplace add Arogus22/bulletproof
```

```bash
claude plugin install bulletproof@bulletproof
```

## Adopt a project

Open Claude Code in the project and run:

```
/bulletproof:framework-init
```

This is the only step that switches the plugin on, and it does it for this project only. It looks at the repository, decides which layers the project needs, writes one small control file (`.framework-version`) at the project root, and tells you what it found:

```
Bulletproof: project adopted.
  .framework-version: /home/you/shop/.framework-version
  proposed layers: [1, 2, 3]
  status:  bootstrapping
  stacks:  node
  detected capabilities:
   + deploy: Cloudflare (api/wrangler.toml)
   + db: Cloudflare D1 (api/wrangler.toml)
  next: Guide active; Exit Lock on standby until the first green /bulletproof:testar.
```

### What the automatic detection looks for

It reads files in the repository (the root and up to three levels below it, skipping `node_modules`, `dist` and the like). It never looks at your machine or your accounts.

| It finds | It concludes |
|---|---|
| `package.json`, `pyproject.toml` / `requirements.txt` / `setup.py`, `Cargo.toml`, `go.mod`, `Gemfile` | the stack (node, python, rust, go, ruby), which decides the test command |
| `wrangler.toml` / `wrangler.jsonc` / `wrangler.json` | the project deploys to production (Cloudflare) |
| `d1_databases` inside the wrangler file | the project has a production database (Cloudflare D1) |
| `drizzle.config.ts`, or a `supabase/`, `prisma/` or `migrations/` folder | the project has a production database |
| `vercel.json` | the project deploys to production (Vercel) |
| a workflow in `.github/workflows` whose file name contains deploy, pages, publish or release | the project deploys to production |

Layers 1 and 2 are always on. Layer 3 (the production guards) is switched on when a deploy or a production database is detected.

Detection cannot see everything. A deploy that leaves no trace in the repository (you upload by hand, a server pulls from git) is invisible to it. So when it finds no deploy or no database, the command **asks you**, and if you say yes it adds layer 3 and the matching configuration. Running `/bulletproof:framework-init` again later is safe: it only adds (a new stack, a newly detected capability) and never removes a layer or a setting that is already in the file.

Commit `.framework-version`. It is the project's setting, shared with everyone who works on it.

### The first green

A freshly adopted project is in `bootstrapping`: the Guide is active, the Exit Lock is on standby, and nothing is blocked. That is deliberate, so that you can adopt a project that has no tests yet. Run:

```
/bulletproof:testar
```

`testar` is Portuguese for "to test". It is the plugin's own verb and it does not collide with anybody else's `/test`. On the first green run the project is promoted to `active` and the Exit Lock arms itself.

The test command comes from the stack:

| Stack | Default command |
|---|---|
| node | `npm test` |
| python | `pytest -q` |
| go | `go test ./...` |
| rust | `cargo test` |
| ruby | `bundle exec rake test` |

If yours is different, set it in `.framework-version`:

```json
"tests": { "python": "python3 -m unittest -q", "node": "npm --prefix api test" }
```

A project with several stacks runs one command per stack, and all of them have to pass.

## The Exit Lock, blocking and releasing

This is the real text, from a project in `active`. The agent changed `cart.py` and tried to commit without testing:

```
$ git add -A && git commit -m "simplify total"

BLOCKED (Exit Lock): this commit touches code that is not proven green. Run
/bulletproof:testar; if it passes, it stamps the green and the commit goes through. If you
already tested and changed the code afterwards, test again.
```

The commit did not happen. The agent runs the tests, and the change turns out to be wrong:

```
/bulletproof:testar

>> [python] python3 -m unittest -q
FAILED (failures=1)

testar: RED. 1 of 1 test suite(s) failed. Nothing stamped; the Exit Lock keeps blocking
code commits. Fix it and run again.
```

That is the point of the whole plugin: the broken commit that would have gone in silently is now a red test the agent has to deal with. It fixes the code and runs the tests again:

```
/bulletproof:testar

>> [python] python3 -m unittest -q
OK
Exit Lock: green stamped for /home/you/shop-api (fp 11de61fb02b3...)

testar: GREEN. Every test suite passed. Green stamped; code commits are now allowed.
```

The same `git add -A && git commit` now goes through. If the agent touches the code again after the green, the stamp stops matching and the commit is blocked again until the new code is tested.

Two details keep it from getting in the way:

- **Only code counts.** The stamp is a fingerprint of the code files that differ from the last commit, by content. Updating the changelog or the docs between the test run and the commit does not invalidate the green, and a commit that touches only docs or config is never policed.
- **New files count.** `git add -A && git commit` with a brand new source file is checked like any other code, even though git has not seen that file yet when the hook runs.

Every block, every red and every green is appended to a local ledger (`~/.claude/state/bulletproof/ledger.jsonl`), so you can later count how many times it actually saved you.

## The layers

Each project switches on the layers it needs. They are listed in `.framework-version` under `layers`.

| Layer | What it is | When it bites | What it lets through |
|---|---|---|---|
| **1** | `/bulletproof:testar`. Before running, it makes the agent check whether the change is covered by a test and write the missing one (testing what the code should do, not photographing what it does; a behaviour that looks wrong becomes a red test reported as a bug candidate). Then it runs every test suite. | Never blocks. Green stamps the code. Red is recorded and nothing is stamped. | |
| **2** | **Exit Lock** (on every Bash command) and the **Guide** (at session start). | `git commit` that touches code with no green stamp for that exact code. Exit code 2: the commit does not run, and the agent is told why and what to do. | Commits of docs and config. Everything while the project is still `bootstrapping`. Any command that is not a commit. |
| **3** | **Production guards.** Only on when the project deploys or has a production database. They never refuse: they hand the decision to you, with a prompt that says what is about to happen. | **Deploy:** `git push` that reaches the protected branch (`main` by default), including an implicit push from that branch, `--all`, `--mirror`; `gh pr merge`; any command in `deploy_cmds` (`wrangler deploy`, `wrangler pages deploy`, `vercel`). **Database (Cloudflare D1):** `wrangler d1 execute --remote` with a write or with `--file`, `migrations apply --remote`, `d1 delete`, `time-travel restore`, `wrangler dev --remote`, `drizzle-kit push / migrate / studio` when the drizzle config uses the `d1-http` driver, and D1 writes through MCP tools. | Pushes to work branches, `--dry-run`, local D1 (no `--remote`), a pure `SELECT` against production, reads and listings. |
| 4, 5 | Staging first, and a guard against known regressions. | Planned, not built yet. | |

The guards read the command line the way it is really written. `git add -A && git commit -m x && git push`, `cd api && npx wrangler deploy`, `npm run deploy` (where the deploy hides inside `package.json`), `git -C <repo> push`, `bash -c "..."` are all seen for what they are. A commit message or a `grep` that merely mentions `wrangler deploy` is not.

What the prompts look like:

```
$ git add -A && git commit -m wip && git push
This `git push` goes (or may go) to `main`, which deploys to PRODUCTION. Approve publishing?

$ npm --prefix api run deploy
`wrangler deploy` publishes straight to production. Project rule: nothing goes to
production without your approval. Approve publishing?

$ npx wrangler d1 execute shop --remote --command "DELETE FROM orders"
This writes to the PRODUCTION database (D1, --remote). Approve this operation?
```

## What it does not do

- **It does not touch a project you have not adopted.** Every hook first looks for a `.framework-version` with `"plugin": "bulletproof"` in it, in the working directory or above it. No file, or a file without that marker, and the hook exits at once: no output, no block, no prompt. Installing the plugin changes nothing in your other projects.
- **It does not refuse deploys or database writes.** Layer 3 asks. You answer.
- **It does not run your tests on commit.** The Exit Lock checks for a stamp, which takes milliseconds. Tests run when `/bulletproof:testar` is called.
- **It does not judge how good your tests are.** The coverage check in `/bulletproof:testar` is an instruction to the agent, not a hook. A project with one trivial test gets a green stamp.
- **It is not a security boundary.** It reads the commands the agent writes. It stops an honest agent making an honest mistake, which is the common case. It does not stop someone who sets out to get around it (a script that commits from inside another program, for instance).
- **The database guard only knows Cloudflare D1** today, and the deploy guard only knows `git push`, `gh pr merge` and the commands listed in `deploy_cmds`. Other platforms are covered as far as you add their deploy command to that list.
- **The Exit Lock fails open.** If it cannot work out the state of the repository, it lets the commit through rather than lock you out. The production guards are the opposite inside an adopted project: when they cannot tell whether a command is safe, they ask.

## Turning it off

| To | Do this |
|---|---|
| switch off one layer in a project | remove its number from `layers` in `.framework-version` (remove `3` to stop the production prompts) |
| put the Exit Lock back on standby | set `"status": "bootstrapping"`; the next green run arms it again |
| release a project completely | delete `.framework-version`, or remove the `"plugin": "bulletproof"` line from it |
| switch the plugin off everywhere | `claude plugin disable bulletproof@bulletproof` (and `enable` to bring it back) |
| remove it | `claude plugin uninstall bulletproof@bulletproof` |

Changes to `.framework-version` take effect on the next command. Disabling or uninstalling takes effect on the next session.

## The control file

`.framework-version`, at the project root, written by `/bulletproof:framework-init`:

```json
{
  "framework": "bulletproof",
  "version": "0.3",
  "plugin": "bulletproof",
  "status": "active",
  "layers": [1, 2, 3],
  "stacks": ["node"],
  "tests": {},
  "config": {
    "code_re": "\\.(ts|tsx|js|jsx|mjs|cjs|svelte|vue|sql|py|go|rs|rb|java|kt|kts|c|cc|cpp|h|hpp|php|cs)$",
    "deploy": {
      "protected_branch": "main",
      "deploy_cmds": ["wrangler deploy", "wrangler pages deploy", "vercel"]
    },
    "prod_db": { "kind": "d1", "guard_remote_only": true }
  }
}
```

| Field | Meaning |
|---|---|
| `plugin` | the marker. Without `"bulletproof"` here, the plugin ignores the project. |
| `status` | `bootstrapping` (Exit Lock on standby) or `active` (Exit Lock armed). Promoted automatically on the first green. |
| `layers` | which layers are on. |
| `stacks`, `tests` | which test suites `/bulletproof:testar` runs, and with which command. |
| `config.code_re` | what counts as code for the Exit Lock. Anything that does not match is docs or config. |
| `config.deploy` | the branch that deploys to production, and the commands that publish by hand. Add your own (`fly deploy`, `netlify deploy --prod`, ...). |
| `config.prod_db` | switches the database guard on. |

Everything else the plugin keeps lives outside your repository, in `~/.claude/state/` (the green stamps and the ledger). Set `BULLETPROOF_STATE` and `BULLETPROOF_LEDGER` to move them.

## Requirements

- Claude Code with plugin support
- Python 3.9 or newer, on the `PATH` as `python3` (standard library only, nothing to `pip install`)
- git
- bash

macOS and Linux. The test suite runs on both on every push. Windows has not been tried; WSL is the likely way in.

## Running the plugin's own tests

Plain Python scripts, no test framework, no network, nothing written outside temporary folders:

```bash
for t in tests/test_*.py; do python3 "$t" | tail -1; done
```

Each file ends with a line such as `==> 40/40 PASS` and exits non-zero on any failure.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal use, research, education, charities and other noncommercial organizations. Commercial use is not allowed, and that includes selling it or offering it as a service.

This makes the project source available, not open source as the OSI defines it, and GitHub lists it as a non-standard license. That is intentional.

Required Notice: Copyright 2026 Rafael (https://github.com/Arogus22)
