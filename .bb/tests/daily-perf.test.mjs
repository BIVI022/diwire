import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
const source = await readFile(new URL("../workflows/daily-perf.js", import.meta.url), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("args", "agent", "log", source.replace("export const meta", "const meta"));
const candidate = { id: "one", hypothesis: "less work", target: "public", risks: "cleanup", acceptance: "declared" };
const result = (outcome) => ({ outcome, summary: "evidence", evidence_path: "/evidence", head_sha: "a".repeat(40), pr: 0, measurement_run_url: "https://example.com/run" });
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
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("rejected"), result("rejected")]);
  assert.equal(value.outcome, "inconclusive");
  assert.deepEqual(calls, ["Findings", "Implementation", "Behavior review", "Implementation"]);
});
test("an inconclusive measurement cannot open a PR", async () => {
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("inconclusive")]);
  assert.equal(value.outcome, "inconclusive");
  assert.ok(!calls.includes("Pull request"));
});
test("an independent audit can stop a nominal measurement win", async () => {
  const {value, calls} = await run([{candidates: [candidate]}, result("ready"), result("accepted"), result("accepted"), result("rejected")]);
  assert.equal(value.outcome, "inconclusive");
  assert.ok(!calls.includes("Pull request"));
});
test("only a full accepted chain opens a PR and defers merge", async () => {
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
