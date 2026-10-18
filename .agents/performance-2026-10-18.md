# Async collection resolution, 18 October 2026

The four tested public `aresolve` collection workloads take 11.551% to 36.629%
less time on this CPython 3.14.7 machine. Each target wins all five paired runs.
This is a warmed, sequential collection result with immediate providers. It is
not a general async, application, network, memory or cross-runtime speed claim.

## Change and risks

`_dependency_value_for_slot_async` used to create an async function and its
closure for each dependency edge, then return that function's coroutine. Make
this helper a direct async function. Keep its operations and order unchanged.
Both callers already await it. No other async helper changes.

Slot and method lookup still happen when the coroutine starts. The async branch
awaits the same value. The sync branch returns its value unchanged, including an
awaitable value. The change adds no cache, task, shared state or suspension point.
Private coroutine names and traceback frames change. Public signatures do not.

Tests check deferred method lookup, exception identity, cancellation and cleanup.
Existing runtime tests cover async dependency graphs, scopes and provider modes.
Independent source review found no semantic defect. It assessed concurrent calls
and plain sync awaitable results from the code rather than new dedicated tests.

The instrumented profile recorded 92,016 consumer resolutions and 920,160 calls
to this helper across the four workloads. The outer helper had 0.256 seconds of
self time. This selected the mechanism; it is not speedup evidence.

## Protocol and environment

Runtime baseline: `634d0b08ed63bbeda07362babe0cec6537722a10`.
Measurement checkpoint: `e32c4d4c72e3d67d27d7f116d3a51706818919a1`.
Only `compiler.py` changes between measurement roles, in the same checkout and
environment. The controller restores the entry source bytes in `finally`.

Source SHA-256:

- Baseline: `08a5259ceb1ae98ba7cbfe46a917d302ec82667df9744111cd8baf4cdf9c34a9`.
- Candidate: `793d68793a97ec4c29c3193042c8ec77d4dbe29e9ab63e881fe03c4344fe5500`.

Environment: macOS 27.0.1 arm64, CPython 3.14.7, AC power, battery 100%.
Interpreter: `/Users/mac/os/projects/diwire/.venv/bin/python`.
Lock SHA-256: `133dd8f6469906bb84d26a89e2ff5ac3e8f92d69d41c61ee83930ebe021dce48`.
No CPU affinity was set. Temperature and CPU frequency were unavailable.
Background services remained active. No concurrent lint, tests or other timing
work was started by this task during official measurements.

The benchmark resolves a transient async consumer with `All[Service]`, collecting
4 or 16 transient components. Component providers are sync or immediate async
functions. It checks collection length, distinct objects within a collection and
new objects across resolutions. Compilation, event-loop creation, checks and
cleanup are outside timing. Driving the loop remains inside timing.

Each fresh process uses three warmup rounds and 20 measured rounds, with one
batch of 1,000 resolutions per round. GC remains enabled. Three baseline processes
calibrate each target. Noise is `100 * (max(process mean) / min(process mean) - 1)`.
Five baseline/candidate pairs alternate order. Every measured round is retained.

Declared acceptance: each target's median paired time reduction must exceed both
3% and its own calibration noise, with at least four of five positive pairs.
Three broad pairs screen protected workloads. Every median throughput loss above
2% requires five focused pairs. Reject a confirmed median loss above 2%. Stop
after one rejected candidate. These rules were recorded before the runtime edit.

## Results

| Components | Provider | Calibration noise | Median time reduction | Median throughput gain | Wins |
| ---: | --- | ---: | ---: | ---: | ---: |
| 4 | sync | 0.626% | 21.344% | 27.136% | 5/5 |
| 4 | async | 0.635% | 11.551% | 13.059% | 5/5 |
| 16 | sync | 5.762% | 36.629% | 57.802% | 5/5 |
| 16 | async | 1.405% | 13.918% | 16.168% | 5/5 |

The larger sync result is consistent with removing about 248-303 ns per edge
at 16 components and 265-318 ns per edge at 4 components. The measurements do not
establish a GC mechanism. One 4-async baseline pair has a 26.021 ms maximum versus
a 10.452 ms median. It remains included; it does not determine the median across
five paired effects. Exact percentages remain limited to this environment.

Broad screening covers 37 cells: 17 canonical, 3 compile, 2 generic compile,
2 registration, 9 async resolution and 4 cache workloads. Eight cells crossed
the confirmation threshold. Their five-pair confirmation medians follow.

| Protected workload | Broad throughput change | Confirmation throughput change |
| --- | ---: | ---: |
| Scoped grid | -2.607% | +0.048% |
| Transient suspending provider | -3.370% | +1.243% |
| Scoped sync provider | -2.977% | -0.585% |
| Scoped async provider | -3.944% | -1.194% |
| Scoped suspending provider | -2.823% | -0.205% |
| Class scope lifecycle | -3.854% | -0.552% |
| Warm request cache, suspending provider | -2.533% | -0.260% |
| Warm request cache, thread lock | -3.042% | -0.361% |

No confirmed median loss exceeds the declared 2% boundary. This does not prove
zero regression. Process drift and individual losses above 2% remain visible.
The ordinary mixed graph improves 4.679% throughput in the broad screen; this
does not support a general async performance claim.

Independent measurement review recomputed all calibration, target, broad and
confirmation results from raw rounds, checked all 37 protected cells, all eight
confirmations, hashes and machine metadata. It found that the declared rules pass.

## Verification and evidence

- `make lint`: pass. Ruff lint, 296 formatted files and strict mypy on 190 files.
- `make test`: 1,177 passed, 99 skipped; 4,099 statements and 1,516 branches,
  100% coverage. Skips include benchmark cases and optional/runtime exclusions.
- Focused candidate check: 209 passed, including benchmark smoke checks.
- Public API snapshot unchanged. SHA-256:
  `762ff10a55b77ab8f1918f834cc2d34dc5fc1906a091af54cc4d1e15b7cc0416`.
- Final `make test-e2e-fastapi`: pass, 5 tests. Containers and network removed.
- Python 3.10 and free-threaded checks remain separate CI merge gates.

Local raw directory:
`/Users/mac/os/.local/diwire/runs/2026-10-18-async-dependency/`.
The compressed archive is
`.agents/performance-evidence/2026-10-18/async-dependency.json.gz`.
It contains every raw timing JSON, summaries, source versions, the controller,
protocol, source and measurement review receipts and validation logs. In the
published environment record, unrelated process paths are reduced to file names.
Timing samples are unchanged.

The controller records the exact commands. The target command is:

```text
uv run --no-sync python -m pytest tests/performance/test_async_collection_workloads.py -k benchmark_diwire --benchmark-only --benchmark-columns=mean,stddev -q --benchmark-json=<fresh-path>.json
```

Use a new output directory for reproduction. The controller refuses to overwrite
raw files. Lint, tests and Docker checks ran after official timings finished.
