export const meta = {
  name: "daily-perf",
  description: "Find, implement, measure and review one small DIWire performance PR.",
  phases: [
    { title: "Findings" },
    { title: "Implementation" },
    { title: "Behavior review" },
    { title: "Validation" },
    { title: "Measurement review" },
    { title: "Pull request" },
  ],
};
const job = args.job;
if (!job || typeof job.job_id !== "string") throw new Error("A dispatcher job is required.");
const context = JSON.stringify(job);
const policy = "Read .bb/automation/prompts/POLICY.md and current AGENTS.md. " +
  "You are a workflow worker in the assigned job worktree. Only the visible root records dispatcher state. " +
  "Do not create schedules, merge, publish or message external channels. " +
  "Keep full evidence at unique paths in BB thread storage. Job context: " + context;
const resultSchema = {
  type: "object", additionalProperties: false,
  required: ["outcome", "summary", "evidence_path", "head_sha", "pr", "measurement_run_url"],
  properties: {
    outcome: { type: "string", enum: ["ready", "accepted", "rejected", "inconclusive", "blocked", "pr_open"] },
    summary: { type: "string" }, evidence_path: { type: "string" }, head_sha: { type: "string" },
    pr: { type: "integer", minimum: 0 }, measurement_run_url: { type: "string" },
  },
};
const findings = await agent(policy + "\nFind evidence-backed performance candidates BEFORE changing code. " +
  "Fetch origin/main. Inspect actual public workloads and profile the suspected costs. " +
  "Read earlier rejected experiments. Choose up to three DISTINCT bounded hypotheses. " +
  "Higher public-workload throughput is primary. For each candidate declare target, protected constraints, " +
  "practical/noise/regression rules and the test plan. Keep source unchanged. Return fewer candidates " +
  "if there is insufficient evidence. Explain omissions. An unrelated release blocker does not stop discovery.", {
  label: "Find performance findings", phase: "Findings", schema: {
    type: "object", additionalProperties: false, required: ["candidates", "summary", "evidence_path"],
    properties: {
      candidates: { type: "array", maxItems: 3, items: {
        type: "object", additionalProperties: false, required: ["id", "hypothesis", "target", "risks", "acceptance"],
        properties: {
          id: { type: "string" }, hypothesis: { type: "string" }, target: { type: "string" },
          risks: { type: "string" }, acceptance: { type: "string" },
        },
      } }, summary: { type: "string" }, evidence_path: { type: "string" },
    },
  },
});
if (!findings || !Array.isArray(findings.candidates)) throw new Error("Findings did not return a valid result.");
const attempts = [];
for (const candidate of findings.candidates) {
  log("Testing hypothesis " + candidate.id + ". All unsuccessful attempts remain in the result.");
  const scope = policy + "\nHypothesis: " + JSON.stringify(candidate) + "\nDiscovery: " + JSON.stringify(findings);
  let implemented = await agent(scope + "\nImplement only this hypothesis. Start from fetched main in an owned clean branch. " +
    "Keep earlier rejected attempts on their own branches with evidence. Add behavior/edge-case tests and a committed " +
    "measurement protocol. Prove the bug/cost mechanism first. Keep harness and runtime edits separate. " +
    "Use the protocol format documented by tools/bb_perf_compare.py. Record all threshold rationale before timing. " +
    "Run focused correctness tests, inspect owned diff, verify Git identity and make a local candidate checkpoint. " +
    "No PR yet. Return ready only when this bounded candidate is testable. Return rejected on semantic failure.", {
    label: "Implement " + candidate.id, phase: "Implementation", schema: resultSchema,
  });
  if (!implemented || implemented.outcome !== "ready") {
    attempts.push({ candidate, implementation: implemented });
    if (!implemented || implemented.outcome === "blocked") return { outcome: "blocked", attempts, findings };
    continue;
  }
  let semantic = await agent(scope + "\nIndependently try to refute correctness of this candidate: " + JSON.stringify(implemented) +
    ". Read the complete diff, lifecycle/cleanup/concurrency/API behavior and focused tests. Probe public boundaries. " +
    "Read raw evidence rather than trusting its summary. Return accepted only with no unresolved supported finding. " +
    "Report concrete counterexamples. Read-only source review; do not modify files.", {
    label: "Review behavior " + candidate.id, phase: "Behavior review", schema: resultSchema,
  });
  if (semantic && semantic.outcome === "rejected") {
    const fixed = await agent(scope + "\nVerify and fix these independent findings once: " + JSON.stringify(semantic) +
      ". Preserve evidence. Update tests and candidate checkpoint. Reject if the mechanism cannot preserve behavior.", {
      label: "Fix behavior " + candidate.id, phase: "Implementation", schema: resultSchema,
    });
    if (fixed && fixed.outcome === "ready") {
      implemented = fixed;
      semantic = await agent(scope + "\nFresh read-only review of exact fixed candidate: " + JSON.stringify(fixed) +
        ". Reproduce the previous findings and inspect the whole final diff. Return accepted only if all are resolved.", {
        label: "Recheck behavior " + candidate.id, phase: "Behavior review", schema: resultSchema,
      });
    }
  }
  if (!semantic || semantic.outcome !== "accepted") {
    attempts.push({ candidate, implementation: implemented, semantic });
    if (!semantic || semantic.outcome === "blocked") return { outcome: "blocked", attempts, findings };
    continue;
  }
  const validation = await agent(scope + "\nValidate this exact candidate: " + JSON.stringify(implemented) +
    ". Read the comparison CLI/workflow interface. Verify source and protocol checkpoints. Run make lint, make test " +
    "with 100% configured coverage and unchanged API signatures, then final make test-e2e-fastapi. Use a unique " +
    "Compose project. Push only the candidate branch with verified owner identity. Dispatch bb-performance.yaml " +
    "against the FULL base/candidate SHAs and committed protocol. Record the actual run ID immediately and reconcile " +
    "it before retry. Wait for that run, download complete raw artifacts, check imported source and dependency hashes, " +
    "every target/protected cell, noise and uncertainty. Treat rejection/inconclusive as such. A successful workflow " +
    "exit or generic competitor report does not prove gain. No same-source favorable-sample rerun. " +
    "No PR yet. Return accepted only on useful public-workload benefit with all gates passing on this head.", {
    label: "Validate and measure " + candidate.id, phase: "Validation", schema: resultSchema,
  });
  if (!validation || validation.outcome !== "accepted") {
    attempts.push({ candidate, implementation: implemented, semantic, validation });
    if (!validation || validation.outcome === "blocked") return { outcome: "blocked", attempts, findings };
    continue;
  }
  const measurement = await agent(scope + "\nIndependently audit the exact-head measurement and correctness receipts: " +
    JSON.stringify(validation) + ". Recompute effects, pair directions, noise and uncertainty from all raw data. " +
    "Verify frozen harness, subjects, runtimes and lock, realistic target and protected workloads, and all quality gates. " +
    "Check exact source head still matches. Refute benchmark gaming and overly broad claims. Read-only. Return accepted " +
    "only if both practical value and absence of unacceptable regression are established.", {
    label: "Audit measurements " + candidate.id, phase: "Measurement review", schema: resultSchema,
  });
  attempts.push({ candidate, implementation: implemented, semantic, validation, measurement });
  if (!measurement || measurement.outcome !== "accepted") {
    if (!measurement || measurement.outcome === "blocked") return { outcome: "blocked", attempts, findings };
    continue;
  }
  const pr = await agent(scope + "\nOpen ONE small PR for the accepted exact candidate. Read both reviews: " +
    JSON.stringify({ semantic, validation, measurement }) + ". Fetch and check current base first. If base or source " +
    "changed, revalidate before claiming acceptance. Reconcile an existing PR for this branch before creating one. " +
    "Use the PR skill. Include measured effects, realistic scope, raw artifact/run links, exact SHAs and quality gates. " +
    "Do not change source or commit a report after measured head without revalidation. Verify configured AI review " +
    "and CI started. Return pr_open with PR number, full head SHA, evidence path and measurement run URL. " +
    "Do not merge. The root records waiting_review; a new follow-up thread will read reviews after ten minutes.", {
    label: "Open measured PR", phase: "Pull request", schema: resultSchema,
  });
  if (!pr || pr.outcome !== "pr_open" || pr.pr <= 0 || !pr.head_sha || !pr.measurement_run_url) {
    return { outcome: "blocked", attempts, findings, pr, reason: "PR receipt incomplete or not validated." };
  }
  return { ...pr, outcome: "waiting_review", attempts, findings };
}
return { outcome: "inconclusive", attempts, findings, reason: "No candidate cleared all declared gates." };
