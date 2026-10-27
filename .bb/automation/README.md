# DIWire performance automation in BB

The owner authorized this workflow on 27 October 2026. It replaces the paused
Codex app schedules. Daily runs use new visible BB project threads and isolated
worktrees. Weekly releases increase the patch version only.

## Components

- `tools/bb_perf_dispatch.py`: short scheduled state check and thread dispatch.
- `.bb/automation/prompts/`: daily, follow-up and patch-release instructions.
- `.bb/workflows/daily-perf.js`: separate findings, implementation, behavior
  review, measurement, independent measurement review and PR stages.
- `tools/bb_perf_compare.py`: frozen baseline/candidate Linux comparison.
- `.github/workflows/bb-performance.yaml`: serialized hosted measurement runner.
- `.bb/automation/merge-gate.mjs`: exact-head review, CI and evidence checks before merge.
- `.bb/automation/install-runtime.mjs`: install a pinned controller and a paused schedule.
- `.bb-env-setup.sh`: frozen dev/docs setup for new BB worktrees.

The visible daily thread owns the job record. Workflow workers return structured
results. Opening a PR records `waiting_review`. A later new follow-up thread uses
the same worktree to read reviews, fix findings, repeat validation and merge.
It checks the actual merge SHA and post-merge CI before completing the job.

## Schedule

The controller checks due work every ten minutes. Daily work becomes due at
09:00 Europe/Minsk, including weekends. Patch releases become due on Monday at
12:00 Europe/Minsk. A delayed scheduler can start due work later. Duplicate ticks
must reconcile the existing job and dispatch receipt instead of starting another
writer. A prior active daily writer defers the next daily run. Rejected,
inconclusive and explicitly blocked jobs do not prevent all future days.

An idle state check uses no model. An unchanged review or pending CI produces a
quiet tick. A model runs only for due work, changed review state or bounded
recovery. Review has a minimum ten-minute wait after a push and a 24-hour deadline.
Reaching that deadline causes a recovery check, not automatic approval.

The BB server and execution machine must be available. Current installation uses
the Mac for coordination and GitHub-hosted Linux for measurements. It does not
move the BB server or enroll a new machine.

## Evidence and acceptance

Read `prompts/POLICY.md` for the authoritative gates. Declare a protocol before
measurement. Record the exact base/candidate SHAs, locked runtime and dependency
fingerprints, frozen harness, target/protected nodes, effect rationale, noise
limit and regression tolerance. Preserve all calibration, failed and successful
samples at unique paths. The comparison result must identify the subject source
that each child process actually imported.

A PR needs useful public-workload improvement beyond noise, unchanged behavior
and API, independent behavior and measurement reviews, clean lint/types, full
coverage, and the final FastAPI E2E check. After PR feedback changes source or
base, evidence must be renewed for the resulting head. Merge needs completed AI
review, green exact-head CI and no unresolved findings. Use match-head-commit.

A release uses the existing GitHub Release -> publish.yaml -> PyPI path. It
checks both registries, useful unreleased changes, exact-SHA CI and known release
blockers. Preserve tag, build, Release, workflow and downloaded PyPI receipts.
A repeat tick reconciles an uncertain publication before any further action.
The historical PR #298 measurement signal remains a release blocker until fresh
controlled evidence clears it. Independent daily work may continue.

## Installation and operations

Install from a reviewed committed revision. The live controller uses a pinned
runtime copy outside Git worktrees. Keep its config, state, job receipts and
installation manifest under an ignored directory such as
`/Users/mac/os/.local/diwire/bb/`. Never put credentials in config or prompts.

Use `node .bb/automation/install-runtime.mjs --project PROJECT_ID --checkout /absolute/source --state-root /absolute/state --provider PROVIDER --model MODEL --reasoning LEVEL` from the clean reviewed worktree. Confirm the provider tuple in the live BB catalog first. Installation creates a BB script automation in the DIWire project, initially paused. The checkout must be an existing root worktree of the same Git repository. Validation happens before an existing schedule is paused. This coordination checkout is used only for fetching; it may have a different HEAD from the reviewed installation worktree. New jobs start from fetched origin/main. The stored
script invokes the pinned dispatcher with its absolute config/state paths and
`tick`. Use cron `*/10 * * * *` with timezone `Europe/Minsk`. Script timeout is
short; agent work runs in BB threads rather than inside the script process.

Before enabling: run dispatcher unit tests and dry-run due checks, validate the
saved workflow, run the workflow control-flow tests, complete all repository
quality gates and exercise the hosted neutral baseline/candidate comparison.
Identical source must not produce an accepted speed claim. Then enable the
controller and inspect the first new daily thread.

For CLI arguments and the exact protocol/config schema, use each tool's `--help`
and its focused unit tests. Status reads are safe. Pause the single BB automation
to stop future dispatches; inspect and stop any already-running job separately.
Keep the old Codex schedules paused to avoid two writers.

## Verification

Run `node --test .bb/tests/daily-perf.test.mjs` and validate the saved workflow with
`bb workflows validate --file .bb/workflows/daily-perf.js` from a BB thread whose
workspace contains that file. Run `make lint` and `make test`. Finish implementation
verification with `make test-e2e-fastapi`. Runtime source is not changed by the
pipeline setup itself.

A configured review marked rate limited or skipped is not approval. A fresh
independent BB AI reviewer may supply the final review instead. The merge helper
checks its completed project thread, report, exact head/base and current review
inventory hash. This fallback preserves review without waiting indefinitely for
a configured reviewer's quota. Missing evidence keeps the PR open.
