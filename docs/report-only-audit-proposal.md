# Proposal: whole-project audit with report only

Status: **proposed, not implemented in 0.4.0**. This is separate from Codex compatibility.

`testar` starts with changed and untracked code, may create missing tests, runs suites,
writes the ledger and green stamp, and can promote adoption status. With no changes it
skips the coverage review. Its final instruction can lead to fixes. It therefore does
not satisfy a whole-project, report-only audit and must not be presented as one.

## Proposed separate workflow

Add an `audit-report` workflow for both hosts, sharing its scope and evidence format:

- Inspect the whole repository at a recorded commit and working-tree state. Inventory
  entry points, application behavior, tests, configuration and external dependencies.
- Read only. No application/test/config edits, adoption changes, ledger entries, green
  stamps, installs, commits or remote actions. Save only the explicitly requested report.
- Separate confirmed defects, hypotheses, existing test failures and unverified risks.
  Each finding needs evidence, location, consequence, confidence and a reproducible
  check when possible. Do not count a speculative concern as a discovered bug.
- Running existing tests is optional and separately bounded: test commands can mutate
  files or contact services. If authorized, run them in a disposable copy with synthetic
  dependencies and record their actual outcome. Never stamp the original project.
- Include coverage limits, skipped areas and relevant tool/runtime versions. A clean
  report is not a guarantee that the project is defect-free.

For a later comparison, freeze the same code state and evaluation rubric, keep the
earlier findings out of the new audit's input, then classify overlap, genuinely new
findings and false positives. Findings and any proposed fixes are separate deliverables.

## Acceptance before implementation is called complete

Use a synthetic repository with independently seeded defects outside the changed
files and at least one plausible false positive. Verify whole-project coverage,
evidence quality, before/after hashes, unchanged adoption/stamps/ledger, and explicit
handling of tests that would write or use external services. Review and authorize this
workflow separately before implementing it.
