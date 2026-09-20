---
description: Runs the project's test layer (Bulletproof), with a coverage self-check first (Step 0). Green stamps and unlocks the commit; red records the failure and keeps the Exit Lock on.
allowed-tools: Bash(python3 *) Bash(git *) Read Grep Glob Edit Write
---

# Testar (Bulletproof)

Runs the current project's test layer, with a coverage self-check BEFORE running it.

## Step 0: coverage self-check

1. See what changed: `git status --short` + `git diff HEAD`. The NEW untracked files
   (`??` in the status) count as a change and `git diff` does not show their contents:
   read them. If nothing changed, skip to Step 1.
2. For each CODE change (new or changed logic, a new flow, a new database write),
   answer: is there a test that exercises this? if this logic breaks, does any test
   go red?
3. If coverage is missing AND WORTH HAVING, write it now, before running, with these
   rules:
   - **Test what the code SHOULD do** (inferred from the name, the context, the types,
     the docs); do not blindly photograph the current output. Anchor each test to what
     it covers (a `# covers: file:line` comment).
   - **Does the current behaviour look WRONG?** Write the test for the correct
     behaviour, leave it red, and report it as a BUG CANDIDATE; the user decides. (The
     red is recorded in the ledger; that is the whole point: catch bugs, do not hide
     them under a test that photographs the defect.)
   - **No theatre:** no tautological tests or trivial asserts just to pad the count. If
     the change has no testable logic (docs, config, style), say so in one line and
     move on.
   - **Not sure what it "should" be? Ask the user,** or protect the current behaviour
     by marking it `# protects current behaviour (unverified)`.
4. Sum up Step 0 in one line: "coverage ok" / "wrote N tests for X" /
   "bug candidate(s): ...".

## Step 1: run the suite and stamp

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/testar.py .
```

## Step 2: report

In plain language: **green** (stamped; if it was the first green, the project was
promoted to "active" and the Exit Lock started policing commits) or **red** (which test
suite failed; if it includes bug candidates from Step 0, list those separately). Fix the code
until it is green, instead of working around the guard.
