import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
const source = await readFile(new URL("../workflows/daily-perf.js", import.meta.url), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("args", "agent", "log", source.replace("export const meta", "const meta"));
const candidate = { id: "one", hypothesis: "less work", target: "public", risks: "cleanup", acceptance: "declared" };
const result = (outcome) => ({ outcome, summary: "evidence", evidence_path: "/evidence", head_sha: "a".repeat(40), pr: 0, measurement_run_url: "https://github.com/maksimzayats/diwire/actions/runs/123" });
async function run(responses) {
  const calls = [];
  const value = await execute({job: {job_id: "daily-2026-10-27"}}, async (prompt, options) => {
    calls.push(options.phase);
    assert.ok(prompt.includes("POLICY.md"));
    assert.ok(responses.length > 0, "Unexpected stage");
    return responses.shift();
  }, () => {});
  assert.equal(responses.length, 0);
  return {value, calls};
}
test("a semantic rejection never reaches measurement or PR", async () => {
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("rejected"), result("rejected"), result("blocked")]);
  assert.equal(value.outcome, "blocked");
  assert.equal(value.attempts[0].fix.outcome, "rejected");
  assert.equal(value.attempts[0].fix.evidence_path, "/evidence");
  assert.deepEqual(calls, ["Findings", "Implementation", "Behavior review", "Implementation", "Example"]);
});
test("an inconclusive measurement cannot open a PR", async () => {
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("inconclusive"), result("blocked")]);
  assert.equal(value.outcome, "blocked");
  assert.ok(!calls.includes("Pull request"));
});
test("an independent audit can stop a nominal measurement win", async () => {
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), result("rejected"), result("blocked")]);
  assert.equal(value.outcome, "blocked");
  assert.ok(!calls.includes("Pull request"));
});
test("a full accepted chain returns a PR checkpoint for root delivery", async () => {
  const pr = {...result("pr_open"), pr: 123};
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), result("accepted"), pr]);
  assert.equal(value.outcome, "waiting_review");
  assert.equal(value.pr, 123);
  assert.deepEqual(calls, ["Findings", "Implementation", "Behavior review", "Validation", "Measurement review", "Pull request"]);
});
test("missing PR metadata blocks completion", async () => {
  const pr = {...result("pr_open"), pr: 123, measurement_run_url: ""};
  const {value} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), result("accepted"), pr]);
  assert.equal(value.outcome, "blocked");
});
test("a blocked candidate stops further writers", async () => {
  const {value, calls} = await run([{candidates: [candidate, {...candidate, id: "two"}]}, result("blocked")]);
  assert.equal(value.outcome, "blocked");
  assert.equal(calls.length, 2);
});

test("a review of a different head cannot authorize validation", async () => {
  const stale = {...result("accepted"), head_sha: "b".repeat(40)};
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), stale]);
  assert.equal(value.outcome, "blocked");
  assert.ok(!calls.includes("Validation"));
});
test("blank evidence cannot enter the accepted chain", async () => {
  const {value} = await run([{candidates: [candidate]}, {...result("ready"), evidence_path: ""}]);
  assert.equal(value.outcome, "blocked");
});
test("a changed head at PR creation cannot become waiting_review", async () => {
  const pr = {...result("pr_open"), pr: 123, head_sha: "b".repeat(40)};
  const {value} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), result("accepted"), pr]);
  assert.equal(value.outcome, "blocked");
});
test("a substituted measurement run cannot pass the independent audit", async () => {
  const audit = {...result("accepted"), measurement_run_url: "https://github.com/maksimzayats/diwire/actions/runs/456"};
  const {value} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), audit]);
  assert.equal(value.outcome, "blocked");
});

test("a blocked behavior fix stops the next candidate", async () => {
  const {value,calls}=await run([{candidates:[candidate,{...candidate,id:"two"}]},result("ready"),result("rejected"),result("blocked")]);
  assert.equal(value.outcome,"blocked");
  assert.equal(value.attempts[0].fix.outcome,"blocked");
  assert.equal(calls.length,4);
});
test("a behavior fix with an invalid ready receipt blocks", async () => {
  const {value}=await run([{candidates:[candidate]},result("ready"),result("rejected"),{...result("ready"),evidence_path:""}]);
  assert.equal(value.outcome,"blocked");
});
test("a successful fix retains its evidence and first review", async () => {
  const {value}=await run([{candidates:[candidate]},result("ready"),result("rejected"),result("ready"),result("accepted"),result("inconclusive"),result("blocked")]);
  assert.equal(value.attempts[0].fix.outcome,"ready");
  assert.equal(value.attempts[0].first_semantic.outcome,"rejected");
});

const exampleResult = outcome => ({...result(outcome), change_kind: "non_runtime", measurement_run_url: ""});
test("empty discovery continues through a useful example PR", async () => {
  const pr = {...exampleResult("pr_open"), pr: 124};
  const {value, calls} = await run([{candidates: []}, exampleResult("ready"), exampleResult("accepted"), exampleResult("accepted"), pr]);
  assert.equal(value.outcome, "waiting_review");
  assert.equal(value.change_kind, "non_runtime");
  assert.match(value.next_action, /through merge and post-merge CI/);
  assert.deepEqual(calls, ["Findings", "Example", "Behavior review", "Validation", "Pull request"]);
});
test("failed measurements stay recorded while a distinct example delivers", async () => {
  const {value} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("inconclusive"),
    exampleResult("ready"), exampleResult("accepted"), exampleResult("accepted"), {...exampleResult("pr_open"), pr: 124}]);
  assert.equal(value.attempts[0].validation.outcome, "inconclusive");
  assert.equal(value.outcome, "waiting_review");
});
for (const [name, mutate] of [
  ["missing scope declaration", r => {delete r.change_kind;}],
  ["false measurement claim", r => {r.measurement_run_url = result("ready").measurement_run_url;}],
  ["missing evidence", r => {r.evidence_path = "";}],
]) test(`${name} cannot start example review`, async () => {
  const preparation = exampleResult("ready"); mutate(preparation);
  const {value,calls} = await run([{candidates: []}, preparation]);
  assert.equal(value.outcome,"blocked");
  assert.deepEqual(calls,["Findings","Example"]);
});
test("example review must bind the exact prepared head", async () => {
  const {value} = await run([{candidates: []}, exampleResult("ready"), {...exampleResult("accepted"),head_sha:"b".repeat(40)}]);
  assert.equal(value.outcome,"blocked");
});
test("example validation failure cannot open a PR", async () => {
  const {value,calls} = await run([{candidates: []}, exampleResult("ready"), exampleResult("accepted"), exampleResult("rejected")]);
  assert.equal(value.outcome,"blocked");
  assert.ok(!calls.includes("Pull request"));
});
test("example PR cannot substitute a different head", async () => {
  const {value} = await run([{candidates: []}, exampleResult("ready"), exampleResult("accepted"), exampleResult("accepted"),
    {...exampleResult("pr_open"),pr:124,head_sha:"b".repeat(40)}]);
  assert.equal(value.outcome,"blocked");
});
