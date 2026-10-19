# Async provider construction, 19 October 2026

The direct async helper meets the declared timing rule. Five alternating fresh-process
pairs show 17.445% and 20.031% less time for warmed public collection resolution with
4 and 16 immediate async transient providers. Each target wins all five pairs.
This is a collection graph result on CPython 3.14.7, not an application or network claim.

## Change and contract

Baseline: `3edede68f54dd63f2efbf657943cca902d6c51fa`.
Only `_build_local_value_async` changes in the library. It becomes a direct async
function instead of creating a nested function and closure for each provider value.
AST checks confirm that the body and parameters are unchanged. All three production
callers await it directly. Provider lookup stays deferred. Return handling, exceptions,
cancellation, scope checks, locks, cache writes and cleanup registration keep their order.
No public API, feature, dependency or benchmark change is included.
Private coroutine names, traceback frames and `inspect.iscoroutinefunction` do change.
No production caller introspects this private helper.

A baseline profile of the same two public workloads recorded 506,088 helper calls,
0.146 seconds of outer-helper self time and 2.136 seconds in its nested body on the
consumer path. Profiling locates cost; its instrumented times are not speedup evidence.

## Frozen protocol and environment

The full card is `hypothesis.md` in the archive. It was saved before runtime edits.
Three same-code baseline processes define noise as
`100 * (max(process mean) / min(process mean) - 1)`.
Five role pairs run B/C, C/B, B/C, C/B, B/C in fresh sequential processes.
Every target must have a median paired time reduction above both its noise and 3%,
with at least four positive pairs. Keep all rounds. Screen all 41 broad cells in
three pairs. Confirm every protected median throughput loss beyond 2% with five
focused pairs. Reject a confirmation median below -2%. Stop after one rejected candidate.
All declared timing conditions passed. Local and independent checks also passed;
full CI and review of the committed head remain merge gates.

Runtime: CPython 3.14.7, GIL enabled, Apple M1 Pro, macOS 27.0.1 arm64.
The same checkout and resolved executable were used for both roles.
Initial and post-timing power: AC, battery 100%.
Lock SHA-256: `133dd8f6469906bb84d26a89e2ff5ac3e8f92d69d41c61ee83930ebe021dce48`.
Baseline compiler SHA-256:
`793d68793a97ec4c29c3193042c8ec77d4dbe29e9ab63e881fe03c4344fe5500`.
Candidate compiler SHA-256:
`9eca2a62091016ff64c0e938e5cf71cf6dce2904b10883b9559230cf84b2d111`.

The initial process snapshot includes mds_stores at 52.5% CPU, a VM at 13.6%
and a Python process at 13.6%. Background work was not stopped. There is no per-run
power, temperature, frequency, affinity or load record. This limits claims about small
protected effects. No local heavy tests, Docker builds or agent profiling ran during
official timing. The focused target CVs range from 0.583% to 5.174%.

## Workload and commands

The existing `test_async_collection_workloads.py` compiles before the timer, creates
one event loop before timing, then measures batches of 1,000 public `aresolve` calls.
Each consumer collects distinct transient component values through `All[Service]`.
It uses 20 measured rounds, three warmups and one iteration. GC stays enabled.
Loop driving is timed; loop creation, compilation, assertions and cleanup are excluded.
Providers return immediately. No concurrent I/O or request latency is measured.

From this repository, the controller runs:

```sh
uv run --no-sync python -m pytest <target-node-ids> -k benchmark_diwire \
  --benchmark-only --benchmark-columns=mean,stddev -q --benchmark-json=<unique-path>.json
```

The exact target node IDs, broad paths and commands are in `experiment.py`.
Start from a clean checkout of the baseline SHA. Put the archived controller and
hypothesis card in a new output directory and run `calibrate`. Save the archived
candidate compiler bytes there as `candidate-compiler.py`, then run `compare`,
`broad`, and `confirm <node-ids from confirmation-targets.json>`.
It writes the exact archived role bytes before each blocking subprocess and restores
entry bytes in `finally`. Baseline and candidate differ in byte count, so timestamp
bytecode cache validation also distinguishes them. Every raw artifact uses a unique path.

## Paired results

| Target | Baseline spread | Median time reduction | Positive pairs |
| --- | ---: | ---: | ---: |
| 4-async | 2.168% | 17.445% | 5/5 |
| 16-async | 1.278% | 20.031% | 5/5 |

Time reduction is `100 * (1 - candidate / baseline)`. Throughput uses the reciprocal
formula. All five target pairs individually exceed 3%. Three broad pairs also show
16.740% and 18.880% target time reductions, each with three positive pairs.
The two sync-component collection screens show throughput changes of +8.960% and
+9.238%; these are protected screening results, not additional calibrated claims.

The broad suite contains 17 canonical, three compile, two generic compile, two
registration, nine aresolve, four cache and four collection cells. Ten apparent
protected losses trigger exactly the following confirmation set:

| Protected cell | Broad throughput | Five-pair confirmation median |
| --- | ---: | ---: |
| `enter_close_scope_resolve_100` | -2.889% | -1.504% |
| `generic_cold_compile[256]` | -3.205% | -0.882% |
| `aresolve_provider[Lifetime.TRANSIENT-sync]` | -2.498% | -0.252% |
| `aresolve_provider[Lifetime.TRANSIENT-suspending]` | -2.905% | +1.598% |
| `aresolve_provider[Lifetime.SCOPED-sync]` | -4.629% | -0.205% |
| `aresolve_provider[Lifetime.SCOPED-async]` | -4.433% | -1.508% |
| `aresolve_provider[Lifetime.SCOPED-suspending]` | -4.547% | -0.182% |
| `aresolve_scope_lifecycle[class]` | -4.671% | -1.335% |
| `aresolve_scope_lifecycle[generator]` | -3.408% | +1.020% |
| `resolve_warm_request_cache_with_thread_lock` | -2.663% | +0.284% |

The worst confirmation median is -1.508%, within the declared -2% boundary.
This is not proof of zero regression. Large individual control swings remain,
including a -18.990% scoped-sync pair (candidate CV 18.586%) and a -10.359%
scoped-async pair (candidate CV 14.214%). No sample, warmup rule or threshold was
changed to remove these outcomes. All 3,390 measured rounds are retained.

## Verification and independent review

- Five new behavior guards also pass against the unchanged baseline.
- Candidate focused checks: 206 passed, including compiler/runtime and API checks.
- `make lint`: Ruff and formatting pass; strict mypy passes 191 source files.
- `make test`: 1,182 passed, 99 skipped; 100% statement and branch coverage
  (4,097 statements, 1,516 branches, none missing).
- Final implementation gate, `make test-e2e-fastapi`: five tests pass in Docker;
  Compose containers and network are removed.
- The public API golden file and lock remain unchanged.
- A separate semantic reviewer verifies source/body equivalence, all callers,
  cleanup/concurrency and API behavior, and independently runs 19 focused checks.
- A separate measurement reviewer recomputes all 372 cell means in 29 process
  artifacts, all 3,390 rounds, calibration, order, pair effects, confirmation set,
  runtime metadata and source role hashes. It reports a measurement pass with the
  environmental limits above. Review receipts are in the archive.

## Evidence

[Compressed raw evidence](performance-evidence/2026-10-19/async-provider.json.gz)
contains role sources, protocol/controller, all raw JSON and summaries, tests,
profile summary, source hashes, review receipts and validation logs.
Archive SHA-256: `3929318521b3c2d71869a1b4163b42fd04e295bc014e98fbd52187402d2b6179`.

`candidate-hashes.json` was captured while the controller had installed baseline
bytes. Its compiler entry is the baseline hash despite the file name. That snapshot
is preserved and explained in `hash-snapshot-note.md`; `final-hashes.json`, archived
source bytes and independently reconstructed role tree hashes identify the candidate.
Unrelated process paths are reduced to basenames only in the published metadata copy.
The original metadata hash is recorded. Timing JSON is unchanged.
Raw local evidence: `/Users/mac/os/.local/diwire/runs/2026-10-19-async-provider/`.
