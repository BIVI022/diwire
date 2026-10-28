# DIWire BB performance policy

Owner instruction: 28 October 2026. Each daily job must deliver one useful PR through review, merge and successful post-merge CI. Daily runs use new visible BB threads in this project. Weekly releases increase PATCH only. This replaces the stopped Codex schedules.

## Authority and scope

The owner authorizes this pipeline to push owned branches, open PRs, address reviews, merge validated changes and publish one weekly patch release through the existing pipeline. Work only in maksimzayats/diwire. Preserve other work and PRs. Read current AGENTS.md and .agents/skills/optimize-performance/SKILL.md. Use the owner Git identity from /Users/mac/os/AGENTS.md. Keep reports in BB. External communications and changes to credentials, branch protection or publication access are outside this task.

## Daily contract

Deliver one small, useful PR each day, including weekends. Prefer a measured throughput gain. Preserve public API, behavior, lifecycle, cleanup, supported Python versions and memory. A rejected or inconclusive experiment is an attempt receipt, not completion of the daily goal. Opening a PR is also not completion. Continue until the PR is merged and CI plus Docs pass on its actual merge SHA, or a concrete external blocker prevents progress.

Work in the assigned isolated BB worktree. Keep one writer. Use no more than three justified hypotheses per daily job. Give each attempt its own branch and evidence directory. State a practical target, protected workloads and acceptance rules before editing. Retain every measured sample and rejected attempt. Move to the next distinct idea after a rejection. For an unstable runner, save an inconclusive attempt receipt and continue with a distinct idea or the example path. A later timing attempt needs a declared environment change and a fixed recovery limit. Never select samples or repeat unchanged source until it passes.

When no performance candidate qualifies, or discovery cannot find another supported idea, continue with a useful runnable example. Inspect current examples, guides and tests first. Choose a missing real use case or an uncovered error/cleanup path. Add the example, focused checks for its behavior and clear usage docs. Regenerate examples/README.md with its generator. Keep failed runtime changes on their own branch and start the example from fetched main. Filler, duplicate examples and unsupported performance claims do not satisfy this goal.

An example PR uses change_kind=non_runtime. Its full base-to-head diff must be limited to examples/, docs/, tests/, .bb/, tools/bb_perf_dispatch.py and README.md. The merge gate verifies all changed and renamed paths from GitHub. Runtime source, dependency, build and CI changes still need the performance path. Require independent semantic review, runnable example checks, clean lint/types, 100% configured coverage, unchanged API signatures, final FastAPI E2E, supported Python CI and exact-head review. Measurement review is not_applicable only after the non-runtime diff is verified. A Linux speed measurement is not required for this path, and no speed gain may be claimed.

Use the Linux comparison workflow for official measurements. Pin full base/candidate SHAs, Python, dependency lock and the frozen test harness. The measured library must come from the intended subject tree. Alternate fresh-process pairs. Require the target gain to exceed declared practical effect and observed baseline noise. Inspect each protected cell and uncertainty. A private helper microbenchmark alone cannot establish an application benefit. Include a public representative workload. Use HTTP throughput and real E2E value when the change affects request handling.

Run make lint, make test with 100% configured coverage and unchanged public API signatures. Run make test-e2e-fastapi as the final implementation check. Use unique Compose project names for concurrent worktrees. Require independent semantic and measurement reviews. Check the supported Python matrix and exact-head remote CI. Keep evidence in BB thread storage and CI artifacts; put concise measured results and limits in the PR body.

## PR review and merge

The visible root owns delivery through merge. After opening a PR, record waiting_review with PR, full head SHA, evidence path, change kind and comparison run URL when applicable. Continue in this root: wait for checks and review, inspect all feedback, fix supported findings and finish the merge gates. A waiting receipt is a checkpoint, not an instruction to end the turn. The dispatcher may start a follow-up only after an interruption or when the root cannot continue because of an external blocker. Give configured AI reviewers at least ten minutes after the latest push, unless failing checks or a new head need earlier work. Time passing is never approval.

Follow-up must read complete configured AI review reports, inline comments, issue comments, unresolved threads, check runs and status contexts. Page through all results. Verify findings before edits. Fix real issues and give evidence for dismissed findings. Resolve a thread only after its finding has a verified answer. A queued review, silence or a generic successful benchmark report is insufficient.

After any source or test change, repeat relevant tests, the complete quality gates and independent reviews against the new head. Performance changes also require renewed performance validation. Non-runtime changes require a fresh full-diff scope check and runnable example checks. Request fresh configured AI review. After a base change, revalidate the resulting candidate. A documentation-only change still needs exact-head CI/review; for a performance PR, a reviewer must prove that earlier runtime measurements remain applicable.

Merge only when all conditions hold for the exact current head:
- the branch contains fetched current main and has no conflicts;
- normal CI and all observed validation checks pass; only documented conditional jobs may be skipped;
- a configured AI reviewer explicitly completed for that head, or a fresh independent BB AI reviewer completed an exact-head and exact-base final review of the complete current PR feedback; independent semantic and measurement reviews must also pass;
- no blocking finding, change request or unresolved review thread remains;
- accepted performance evidence, or verified non-runtime scope and runnable example evidence, and final E2E evidence apply to this head.

Use the normal squash method with --match-head-commit FULL_SHA. Use no admin bypass, force push or protection change. Check the squash message for machine/agent coauthors. Read back merge state and SHA. Mark complete only after CI and Docs pass on the actual merge SHA. Record waiting_ci otherwise. Keep a blocked PR open with a specific next action.

## State and recovery

Only the visible root job thread records dispatcher state. Workflow workers return structured results to the root. Read the appended job JSON for config/state paths and the record command. Record current BB_THREAD_ID and BB_ENVIRONMENT_ID, actual workspace, exact PR head and evidence. A new follow-up thread can use the same worktree after interruption; each day starts in a fresh visible thread. Worker errors must not become accepted results. Record blocked with the exact external failure and a bounded recovery action only when neither the performance path nor the example path can continue. When the owner explicitly resumes a failed job, use record --reopen --status running with the current saved root identity and the owner's reason. Preserve all earlier receipts.

PR #298 has an unresolved historical settings-registration performance signal. Read its saved measurement receipt before related work. Keep it as a release blocker until a controlled current-source comparison or validated fix clears it. It does not block independent daily hypotheses.

A green CodeRabbit status that says rate limited or skipped is not completed review. When the configured reviewer cannot run, use a separate read-only BB AI review thread in this project. Its report must bind the full head, base and current review inventory hash, contain no blocking finding, and identify its reviewer thread. Supply that actual report through independent_ai_review_path to the merge helper. A timeout or missing report is never approval.
