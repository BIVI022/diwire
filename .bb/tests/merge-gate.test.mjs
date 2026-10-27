import assert from "node:assert/strict";
import test from "node:test";
import { evaluate, reviewInventoryHash, readSnapshot } from "../automation/merge-gate.mjs";
const head = "a".repeat(40);
const base = "b".repeat(40);
const now = Date.parse("2026-10-27T12:00:00Z");
const required = [...["3.10", "3.11", "3.12", "3.13", "3.13t", "3.14", "3.14t", "3.15", "3.15t"].map(v => `Lint & Tests (Python ${v})`), "E2E FastAPI (Docker Compose, Python 3.14)", "E2E aiohttp (Docker Compose, Python 3.14)", "E2E Celery (Docker Compose, Python 3.14)", "Docs Build"];
function fixture() {
  const snapshot = {
    pr: {headRefOid: head, baseRefOid: base, baseRefName: "main", state: "OPEN", isDraft: false, mergeable: "MERGEABLE", reviewDecision: ""},
    currentMain: base, baseComparison: {status: "ahead"}, headPushedAt: "2026-10-27T11:40:00Z", reviewNotBefore: "2026-10-27T11:50:00Z",
    checks: required.map(name => ({name, status: "completed", conclusion: "success"})),
    statuses: [{context: "CodeRabbit", state: "success"}],
    reviews: [{id: "review1", author: {login: "coderabbitai"}, commit: {oid: head}, state: "COMMENTED"}],
    comments: [{id: "comment1"}], threads: [{isResolved: true, comments: [{id: "inline1"}]}],
    measurementRun: {headSha: head, status: "completed", conclusion: "success", workflowPath: ".github/workflows/bb-performance.yaml", event: "workflow_dispatch"},
    measurementArtifactsVerified: true,
    measurementDecision: {status: "accepted", identical_source: false, base_sha: base, candidate_sha: head, protocol_sha256: "d".repeat(64)},
  };
  const evidence = {review_not_before: "2026-10-27T11:50:00Z", head_sha: head, base_sha: base, measurement: {outcome: "accepted", candidate_sha: head, base_sha: base, run_url: "https://github.com/maksimzayats/diwire/actions/runs/123", protocol_sha256: "d".repeat(64)}, fastapi_e2e_head: head, evidence_directory: "/proof", reviewed_comment_ids: ["comment1", "inline1"], reviewed_review_ids: ["review1"]};
  for (const key of ["semantic_review", "measurement_review", "lint", "tests", "api_signatures", "fastapi_e2e", "all_review_comments_read", "all_findings_addressed"]) evidence[key] = "passed";
  evidence.review_inventory_sha256 = reviewInventoryHash(snapshot);
  return {snapshot, evidence};
}
test("complete exact-head evidence passes", () => {
  const {snapshot, evidence} = fixture();
  assert.deepEqual(evaluate(snapshot, evidence, head, now).errors, []);
});
for (const [name, mutate] of [
  ["new push", f => {f.snapshot.pr.headRefOid = "c".repeat(40);}],
  ["new main", f => {f.snapshot.currentMain = "c".repeat(40);}],
  ["unresolved thread", f => {f.snapshot.threads[0].isResolved = false;}],
  ["edited comment", f => {f.snapshot.comments[0].body = "new issue";}],
  ["new unread comment", f => {f.snapshot.comments.push({id: "new"});}],
  ["queued AI review", f => {f.snapshot.reviews = []; f.snapshot.statuses[0].state = "pending";}],
  ["missing CI", f => {f.snapshot.checks.pop();}],
  ["skipped E2E", f => {f.snapshot.checks[9].conclusion = "skipped";}],
  ["waiting period", f => {f.snapshot.reviewNotBefore = "2026-10-27T12:05:00Z"; f.evidence.review_not_before = f.snapshot.reviewNotBefore;}],
  ["stale measurement", f => {f.evidence.measurement.candidate_sha = base;}],
  ["ordinary CI used as measurement", f => {f.snapshot.measurementRun.workflowPath = ".github/workflows/ci.yaml";}],
  ["missing artifact proof", f => {f.snapshot.measurementArtifactsVerified = false;}],
  ["nonaccepted remote decision", f => {f.snapshot.measurementDecision.status = "inconclusive";}],
  ["different protocol", f => {f.snapshot.measurementDecision.protocol_sha256 = "e".repeat(64);} ],
  ["failed measurement run", f => {f.snapshot.measurementRun.conclusion = "failure";}],
  ["unresolved change request", f => {f.snapshot.reviews.push({id: "r2", author: {login: "human"}, state: "CHANGES_REQUESTED"});}],
]) test(`${name} prevents merge`, () => {
  const f = fixture(); mutate(f);
  assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
});
test("documented conditional skips are allowed", () => {
  const {snapshot, evidence} = fixture();
  snapshot.checks.push({name: "dependabot-auto-merge", status: "completed", conclusion: "skipped"});
  assert.equal(evaluate(snapshot, evidence, head, now).ready, true);
});

test("review comments are fully paged even in a resolved thread", () => {
  const connection = (nodes, more = false) => ({nodes, pageInfo: {hasNextPage: more, endCursor: more ? "next-page" : null}});
  const request = args => {
    if (args[0] === "pr") return fixture().snapshot.pr;
    if (args[1].endsWith("/commits/main")) return {sha: base};
    if (args[1].includes("/compare/")) return {status: "ahead"};
    if (args[1].includes("check-runs")) return [{check_runs: []}];
    if (args[1].includes("/statuses")) return [[]];
    const query = args.find(a => a.startsWith("query="));
    if (query.includes("node(id:")) {
      const second = args.includes("cursor=next-page");
      return {data: {node: {comments: connection(second ? [{id: "last"}] : Array.from({length:100}, (_,i) => ({id: String(i)})), !second)}}};
    }
    if (query.includes("reviewThreads(")) return {data: {repository: {pullRequest: {reviewThreads: connection([{id: "thread", isResolved: true, comments: connection([], true)}])}}}};
    const field = query.includes("reviews(") ? "reviews" : "comments";
    return {data: {repository: {pullRequest: {[field]: connection([])}}}};
  };
  const snapshot = readSnapshot("maksimzayats/diwire", 123, head, undefined, "2026-10-27T11:50:00Z", request);
  assert.equal(snapshot.threads[0].comments.length, 101);
  assert.equal(snapshot.threads[0].comments[100].id, "last");
});
