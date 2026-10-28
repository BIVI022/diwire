export const meta = {
  name: "daily-perf",
  description: "Deliver a useful daily PR. Prefer measured performance; otherwise add a runnable example.",
  phases: [
    { title: "Findings" },
    { title: "Implementation" },
    { title: "Behavior review" },
    { title: "Validation" },
    { title: "Measurement review" },
    { title: "Pull request" },
    { title: "Example" },
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
    change_kind: { type: "string", enum: ["performance", "non_runtime"] },
  },
};
const fullSha = /^[0-9a-f]{40}$/;
const runUrl = /^https:\/\/github.com\/maksimzayats\/diwire\/actions\/runs\/\d+$/;
function receipt(result, expectedHead, measured = false) {
  return result && typeof result.evidence_path === "string" && result.evidence_path.startsWith("/") &&
    fullSha.test(result.head_sha) && (!expectedHead || result.head_sha === expectedHead) &&
    (!measured || runUrl.test(result.measurement_run_url));
}
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
  if (implemented?.outcome === "ready" && !receipt(implemented)) return { outcome: "blocked", attempts, findings, reason: "Implementation receipt is incomplete." };
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
  const firstSemantic = semantic;
  let fixed = null;
  if (semantic && semantic.outcome === "rejected") {
    fixed = await agent(scope + "\nVerify and fix these independent findings once: " + JSON.stringify(semantic) +
      ". Preserve evidence. Update tests and candidate checkpoint. On rejection verify exact owned rollback; return blocked if worktree state is uncertain.", {
      label: "Fix behavior " + candidate.id, phase: "Implementation", schema: resultSchema,
    });
    if (fixed && fixed.outcome === "ready" && receipt(fixed)) {
      implemented = fixed;
      semantic = await agent(scope + "\nFresh read-only review of exact fixed candidate: " + JSON.stringify(fixed) +
        ". Reproduce the previous findings and inspect the whole final diff. Return accepted only if all are resolved.", {
        label: "Recheck behavior " + candidate.id, phase: "Behavior review", schema: resultSchema,
      });
    } else {
      attempts.push({ candidate, implementation: implemented, semantic, fix: fixed });
      if (!fixed || !["rejected", "inconclusive"].includes(fixed.outcome)) return { outcome: "blocked", attempts, findings, reason: "Behavior fix did not return a valid ready receipt or safe rejection." };
      continue;
    }
  }
  if (semantic?.outcome === "accepted" && !receipt(semantic, implemented.head_sha)) return { outcome: "blocked", attempts, findings, reason: "Behavior review does not match candidate head." };
  if (!semantic || semantic.outcome !== "accepted") {
    attempts.push({ candidate, implementation: implemented, semantic, first_semantic: firstSemantic, fix: fixed });
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
    "No PR yet. Return accepted only on useful public-workload benefit with local gates and official measurements passing. " +
    "Supported Python remote CI and normal exact-head checks start after PR creation and remain mandatory root merge gates.", {
    label: "Validate and measure " + candidate.id, phase: "Validation", schema: resultSchema,
  });
  if (validation?.outcome === "accepted" && !receipt(validation, implemented.head_sha, true)) return { outcome: "blocked", attempts, findings, reason: "Validation does not match candidate head or run." };
  if (!validation || validation.outcome !== "accepted") {
    attempts.push({ candidate, implementation: implemented, semantic, first_semantic: firstSemantic, fix: fixed, validation });
    if (!validation || validation.outcome === "blocked") return { outcome: "blocked", attempts, findings };
    continue;
  }
  const measurement = await agent(scope + "\nIndependently audit the exact-head measurement and correctness receipts: " +
    JSON.stringify(validation) + ". Recompute effects, pair directions, noise and uncertainty from all raw data. " +
    "Verify frozen harness, subjects, runtimes and lock, realistic target and protected workloads, and all quality gates. " +
    "Check exact source head still matches. Refute benchmark gaming and overly broad claims. Read-only. Return accepted " +
    "only if both practical value and absence of unacceptable regression are established. Supported Python remote CI runs after PR creation and remains a root merge gate.", {
    label: "Audit measurements " + candidate.id, phase: "Measurement review", schema: resultSchema,
  });
  attempts.push({ candidate, implementation: implemented, semantic, first_semantic: firstSemantic, fix: fixed, validation, measurement });
  if (measurement?.outcome === "accepted" && (!receipt(measurement, validation.head_sha, true) || measurement.measurement_run_url !== validation.measurement_run_url)) return { outcome: "blocked", attempts, findings, reason: "Independent audit does not match measured head/run." };
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
    "Do not merge from this worker. The root records waiting_review, then continues in this same root through review, fixes, merge and post-merge checks using FOLLOWUP.md.", {
    label: "Open measured PR", phase: "Pull request", schema: resultSchema,
  });
  if (!pr || pr.outcome !== "pr_open" || pr.pr <= 0 || !receipt(pr, validation.head_sha, true) || pr.measurement_run_url !== validation.measurement_run_url) {
    return { outcome: "blocked", attempts, findings, pr, reason: "PR receipt incomplete or not validated." };
  }
  return { ...pr, change_kind: "performance", outcome: "waiting_review", attempts, findings, next_action: "Root must continue with FOLLOWUP.md through merge and post-merge CI. This is a checkpoint, not completion." };
}
// Failed performance attempts remain evidence. They do not finish the daily job.
const fallbackScope = policy + "\nNo performance candidate qualified. Preserve all attempts: " + JSON.stringify(attempts) +
  "\nDiscovery: " + JSON.stringify(findings);
const example = await agent(fallbackScope + "\nContinue with a useful runnable example. Inspect current examples, guides and tests. " +
  "Choose a missing real scenario or an uncovered error/cleanup case. State its user value and checks before editing. " +
  "Keep rejected runtime work on its own branch. Start from fetched main on a new owned clean branch. " +
  "Use only the non-runtime paths allowed by POLICY.md. Add the example, behavior tests and usage docs; regenerate " +
  "examples/README.md with its generator. Prove runtime source, dependencies, build and CI remain unchanged. " +
  "Run focused example checks, inspect the whole diff, verify owner identity and commit. Return ready with " +
  "change_kind=non_runtime and an empty measurement_run_url. Make no speed claim. No PR yet.", {
  label: "Implement useful example", phase: "Example", schema: resultSchema,
});
function exampleReceipt(value, head) {
  return receipt(value, head) && value.change_kind === "non_runtime" && value.measurement_run_url === "";
}
if (example?.outcome !== "ready" || !exampleReceipt(example)) return {outcome: "blocked", attempts, findings, example, reason: "Example preparation failed or its receipt is incomplete."};
const exampleReview = await agent(fallbackScope + "\nIndependently review this exact example candidate: " + JSON.stringify(example) +
  ". Check actual user value, lack of duplication, full diff, public behavior and error/cleanup assertions. " +
  "Verify all changed and renamed paths satisfy POLICY.md non-runtime scope. Run independent checks. Read-only source. " +
  "Return accepted only with no supported finding, change_kind=non_runtime and empty measurement_run_url.", {
  label: "Review useful example", phase: "Behavior review", schema: resultSchema,
});
if (exampleReview?.outcome !== "accepted" || !exampleReceipt(exampleReview, example.head_sha)) return {outcome: "blocked", attempts, findings, example, exampleReview, reason: "Example review did not pass. Root must fix supported findings and continue."};
const exampleValidation = await agent(fallbackScope + "\nValidate the exact reviewed example: " + JSON.stringify({example, exampleReview}) +
  ". Run runnable example and behavior checks, make lint, make test with 100% configured coverage and unchanged API signatures, " +
  "then final make test-e2e-fastapi with a unique Compose project. Verify clean scope and exact head. Push only the owned " +
  "branch with owner identity. Return accepted, change_kind=non_runtime, empty measurement_run_url and full evidence. " +
  "No performance timing is needed for a verified non-runtime diff. No PR yet.", {
  label: "Validate useful example", phase: "Validation", schema: resultSchema,
});
if (exampleValidation?.outcome !== "accepted" || !exampleReceipt(exampleValidation, example.head_sha)) return {outcome: "blocked", attempts, findings, example, exampleReview, exampleValidation, reason: "Example validation did not pass. Root must fix the failed gate and continue."};
const examplePr = await agent(fallbackScope + "\nOpen one useful example PR for this exact validated head: " +
  JSON.stringify({example, exampleReview, exampleValidation}) + ". Fetch main first; if base changed, revalidate the resulting head. " +
  "Reconcile existing PRs for the branch. Use the PR skill. Explain the missing case, checks and unchanged runtime scope. " +
  "Include earlier experiment evidence as context without a speed claim. Verify CI and configured review started. " +
  "Return pr_open with change_kind=non_runtime, exact head, PR number, evidence and empty measurement_run_url. " +
  "This worker does not merge. The visible root continues through review, exact-head merge and post-merge CI.", {
  label: "Open useful example PR", phase: "Pull request", schema: resultSchema,
});
if (examplePr?.outcome !== "pr_open" || examplePr.pr <= 0 || !exampleReceipt(examplePr, example.head_sha)) return {outcome: "blocked", attempts, findings, examplePr, reason: "Example PR receipt is incomplete."};
return {...examplePr, outcome: "waiting_review", attempts, findings, example, exampleReview, exampleValidation,
  next_action: "Root must continue with FOLLOWUP.md through merge and post-merge CI. This is a checkpoint, not completion."};
