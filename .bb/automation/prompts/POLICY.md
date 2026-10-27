# DIWire BB performance policy

Owner instruction: 27 October 2026. Daily runs use new visible BB threads in this project. Weekly releases increase PATCH only. This replaces the stopped Codex schedules.

## Authority and scope

The owner authorizes this pipeline to push owned branches, open PRs, address reviews, merge validated changes and publish one weekly patch release through the existing pipeline. Work only in maksimzayats/diwire. Preserve other work and PRs. Read current AGENTS.md and .agents/skills/optimize-performance/SKILL.md. Use the owner Git identity from /Users/mac/os/AGENTS.md. Keep reports in BB. External communications and changes to credentials, branch protection or publication access are outside this task.

## Daily contract

Aim for one small PR with a useful, measured throughput gain each day, including weekends. Preserve public API, behavior, lifecycle, cleanup, supported Python versions and memory. A proven bug fix belongs here only if it also has a measured performance benefit or fixes a known performance regression. Useful attempts, rejected ideas and clear blockers are valid outcomes. Empty PRs and unproved speed claims are not.

Work in the assigned isolated BB worktree. Keep one writer. Use no more than three justified hypotheses per daily job. Give each attempt its own branch and evidence directory. State a practical target, protected workloads and acceptance rules before editing. Retain every measured sample and rejected attempt. Move to the next distinct idea after a rejection. For an unstable runner, preserve evidence and record an inconclusive result; a later attempt needs a declared environment change and a fixed recovery limit. Never select samples or repeat unchanged source until it passes.

Use the Linux comparison workflow for official measurements. Pin full base/candidate SHAs, Python, dependency lock and the frozen test harness. The measured library must come from the intended subject tree. Alternate fresh-process pairs. Require the target gain to exceed declared practical effect and observed baseline noise. Inspect each protected cell and uncertainty. A private helper microbenchmark alone cannot establish an application benefit. Include a public representative workload. Use HTTP throughput and real E2E value when the change affects request handling.

Run make lint, make test with 100% configured coverage and unchanged public API signatures. Run make test-e2e-fastapi as the final implementation check. Use unique Compose project names for concurrent worktrees. Require independent semantic and measurement reviews. Check the supported Python matrix and exact-head remote CI. Keep evidence in BB thread storage and CI artifacts; put concise measured results and limits in the PR body.

## PR review and merge

Opening a PR ends the initial daily stage. Record waiting_review with PR, full head SHA, evidence path and comparison run URL. Give configured AI reviewers at least ten minutes after the latest push, unless failing checks or a new head need earlier work. Time passing is never approval.

Follow-up must read complete configured AI review reports, inline comments, issue comments, unresolved threads, check runs and status contexts. Page through all results. Verify findings before edits. Fix real issues and give evidence for dismissed findings. Resolve a thread only after its finding has a verified answer. A queued review, silence or a generic successful benchmark report is insufficient.

After any source or test change, repeat relevant tests, the complete quality gates, independent reviews and performance validation against the new head. Request fresh configured AI review. After a base change, revalidate the resulting candidate. A documentation-only change still needs exact-head CI/review; a reviewer must prove that earlier runtime measurements remain applicable.

Merge only when all conditions hold for the exact current head:
- the branch contains fetched current main and has no conflicts;
- normal CI and all observed validation checks pass; only documented conditional jobs may be skipped;
- a configured AI reviewer explicitly completed for that head, and independent semantic and measurement reviews pass;
- no blocking finding, change request or unresolved review thread remains;
- accepted performance evidence and final E2E evidence apply to this head.

Use the normal squash method with --match-head-commit FULL_SHA. Use no admin bypass, force push or protection change. Check the squash message for machine/agent coauthors. Read back merge state and SHA. Mark complete only after CI and Docs pass on the actual merge SHA. Record waiting_ci otherwise. Keep a blocked PR open with a specific next action.

## State and recovery

Only the visible root job thread records dispatcher state. Workflow workers return structured results to the root. Read the appended job JSON for config/state paths and the record command. Record current BB_THREAD_ID and BB_ENVIRONMENT_ID, actual workspace, exact PR head and evidence. A new follow-up thread can use the same worktree; each day uses a fresh visible thread. Worker errors must not become accepted results. Leave a durable blocked or inconclusive receipt before ending on a blocker.

PR #298 has an unresolved historical settings-registration performance signal. Read its saved measurement receipt before related work. Keep it as a release blocker until a controlled current-source comparison or validated fix clears it. It does not block independent daily hypotheses.
