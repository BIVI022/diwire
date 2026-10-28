# Cold scoped async leaf factory experiment - 2026-10-28

Accepted for the measured Linux fresh-request-scope workload. No general library or production HTTP throughput claim.

## Mechanism and provenance

Baseline: `2dc938211a2cfb82b89323d025ac434c6dd246d1` (current `origin/main` when cloned). Candidate: the commit containing this report; its exact commit SHA is in the PR description. All seven implementation file hashes and both source trees are anchored in the raw archive.

Two added runtime lines directly await async factories inside the existing empty-plan, empty-dependencies, non-injection-wrapper guard. Provider lookup and instance handling precede the guard. Cache writes, missing sentinel, ownership/delegation, locks and double-check, cancellation/error propagation, arguments, generators and context managers keep existing paths. Profile: 16,000 provider calls in both variants; selected helper/nested coroutine calls 16,000 to zero.

Environment: Docker Desktop Linux aarch64 VM (`6.3.13-linuxkit`, glibc 2.36) on Apple M1 Pro; CPython 3.14.2, GIL enabled; both variants pinned to CPU `{2}`, four-CPU VM. AC power reported, low-power mode off; physical frequency/power policy uncontrolled. Identical frozen dev/docs dependency versions, separate `/env/base` and `/env/cand` environments, equal-length checkout names. Both imports verified from intended checkout. No timing alongside builds, tests, profilers, or CPU-heavy reviewers.

Hashes (SHA-256):

- Lock: `cf9a1213adc6db758b8c4ad51f6f6d6a2809bc23fa5aa55fb6742b8dcde16c83`.
- Baseline compiler: `3bdd5fa42da1d3df18e446dcb28f42f08a0629c27a78771c18e4a3f5c9888e0a`.
- Candidate compiler: `1728961053b7daa6945e7b1c364efb91a03474d9fc937443d4210805af455ba8`.
- Identical benchmark harness: `98444fa81b39189d30119e06d256f45f400e274c20bd4e5f0a67d67ba5cda888`.
- Seven-file implementation patch: `0ddf2d4b7e513a47f3f9ece5c2c0dc1a90229f0cbda9a0db2269b1f4af74ac88`.

## Protocol and target

The protocol was written before the runtime edit. Three baseline calibration processes; seven fixed alternating target pairs in fresh processes; median paired gain `(base median / candidate median - 1) * 100`. Seed 20261027, 20,000 bootstrap resamples of process-pair gains; quantiles 499 and 19499. Primary acceptance: at least 3% median gain, at least 6/7 positive, interval above zero, calibration range at most 10%. One hypothesis only. Every raw sample, setup failure and negative screen retained.

Primary ASYNC-16 calibration range: **3.032908%**. Primary gain: **11.750710%**, **7/7 positive**, 95% bootstrap interval **[10.657935%, 14.069420%]**. Median batch times: 0.001459449317 -> 0.001286583333 seconds per 32 complete fresh request scopes. Ratios use paired medians, not the ratio of separate medians.

Registration/compilation excluded; entry, root resolution, cold cache construction and exit included. Each primary scope resolves one compiled root with sixteen scoped async leaves and ASYNC locking. `sleep(0)` is only a scheduler guard. ASGI includes JSON checks and request/response handling, excludes sockets/Uvicorn/network delay and production concurrency.

| Target cell | Calibration range % | Median paired gain % | Positive | Bootstrap 95% interval % | All paired gains % |
| --- | ---: | ---: | ---: | --- | --- |
| `test_cached_async_leaf_scope[LockMode.NONE-1]` | 9.2400 | +9.8322 | 6/7 | +5.9553, +12.8365 | -9.6194, +11.7745, +5.9553, +9.8322, +7.1680, +17.0474, +12.8365 |
| `test_cached_async_leaf_scope[LockMode.NONE-16]` | 3.9924 | +14.8426 | 6/7 | +7.0822, +18.1845 | -9.2620, +7.0822, +16.8751, +13.8810, +18.1845, +14.8426, +20.5496 |
| `test_cached_async_leaf_scope[LockMode.ASYNC-1]` | 2.8787 | +5.3498 | 6/7 | +3.2026, +8.9682 | -4.0321, +4.8501, +5.3498, +7.4043, +3.2026, +9.7748, +8.9682 |
| `test_cached_async_leaf_scope[LockMode.ASYNC-16]` | 3.0329 | +11.7507 | 7/7 | +10.6579, +14.0694 | +2.9136, +14.0694, +12.5484, +11.7507, +10.6579, +11.7398, +14.9549 |
| `test_cached_async_leaf_suspending` | 0.2227 | +7.8276 | 6/7 | +6.6627, +9.6756 | -10.5428, +6.6627, +9.6756, +7.3770, +8.7863, +7.8276, +10.4439 |
| `test_cached_async_leaf_fastapi_asgi` | 1.0192 | +4.7274 | 7/7 | +1.2756, +7.0874 | +7.0874, +0.8605, +4.5900, +1.2756, +4.7274, +8.5525, +5.1021 |

## Every protected workload

Three fixed alternating screening pairs per broader cell. Every median below -2% triggers seven fixed confirmation pairs; confirmed median must be at least -2%. This is a point-estimate decision rule, not a confidence bound on maximum slowdown. All six target cells passed protection directly.

| Broader cell | Screen median % | All 3 screening gains % | Confirmation median %, if triggered | Decision |
| --- | ---: | --- | --- | --- |
| `test_benchmark_diwire_enter_close_scope_no_resolve` | -0.6002 | +3.2132, -0.6002, -3.6747 | Not triggered | PASS |
| `test_benchmark_diwire_enter_close_scope_resolve_100` | +1.3356 | +0.5167, +1.3356, +2.8106 | Not triggered | PASS |
| `test_benchmark_diwire_enter_close_scope_resolve_generator_request_try_finally` | -0.5787 | -3.1076, +5.1436, -0.5787 | Not triggered | PASS |
| `test_benchmark_diwire_enter_close_scope_resolve_once` | -1.1105 | -1.0225, -1.1105, -11.0167 | Not triggered | PASS |
| `test_benchmark_diwire_enter_close_scope_resolve_open_generic_scoped` | -0.5122 | -1.7840, +0.0816, -0.5122 | Not triggered | PASS |
| `test_benchmark_diwire_enter_close_scope_resolve_scoped_100` | -0.2618 | -0.2618, -4.4909, -0.1880 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_deep_transient_chain` | -0.1712 | -66.5839, -0.1712, +1.1922 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_generated_scoped_grid` | -0.2249 | -6.0975, -0.2249, +7.0132 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_mixed_lifetimes` | -1.4215 | -2.5416, -1.4215, +1.0436 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_open_generic_transient` | +1.6265 | -5.3964, +1.6265, +2.4469 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_scoped` | -1.5512 | -1.2243, -1.6488, -1.5512 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_scoped_with_registered_open_closed_generics` | -1.7693 | -2.6257, -1.7693, -0.3530 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_scoped_with_registered_open_closed_generics_pair_alternating` | +0.1784 | +0.3229, -0.4869, +0.1784 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_scoped_with_registered_open_closed_generics_pair_same` | +0.1241 | +1.8637, +0.1241, -2.2633 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_singleton` | +0.2797 | -1.7367, +0.2797, +3.1736 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_transient` | -1.4510 | -1.4510, -8.6862, -0.2332 | Not triggered | PASS |
| `test_benchmark_diwire_resolve_wide_transient_graph` | -0.7074 | -0.7074, -4.0117, +1.3748 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.TRANSIENT-sync]` | -0.1194 | +1.8329, -0.1194, -1.3003 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.TRANSIENT-async]` | +0.9573 | +4.2622, -4.4873, +0.9573 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.TRANSIENT-suspending]` | -1.2199 | -1.2199, -0.6510, -3.2748 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.SCOPED-sync]` | +0.0621 | +0.4506, +0.0621, -1.5356 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.SCOPED-async]` | -0.0548 | +0.9023, -1.1434, -0.0548 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_provider[Lifetime.SCOPED-suspending]` | -0.7113 | -1.3622, +4.3549, -0.7113 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_mixed_graph` | +1.1807 | +0.4743, +1.1807, +2.9286 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_scope_lifecycle[class]` | -3.1338 | -3.4594, -3.1338, +2.0398 | -0.6687 | PASS |
| `test_benchmark_diwire_aresolve_scope_lifecycle[generator]` | +0.0917 | -1.2380, +0.0917, +0.1532 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_dispatch_patterns[same_identity]` | -2.5482 | +4.6430, -2.5482, -3.9385 | -0.8737 | PASS |
| `test_benchmark_diwire_aresolve_dispatch_patterns[same_equality]` | +0.7388 | +1.1520, +0.7388, -2.2177 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_dispatch_patterns[alternate_identity_equality]` | -0.5291 | -0.5291, +0.6024, -1.9331 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_dispatch_patterns[alternate_equal_aliases]` | +0.6973 | -1.2673, +0.6973, +4.2571 | Not triggered | PASS |
| `test_benchmark_diwire_aresolve_dispatch_patterns[mixed_cached]` | +1.1482 | +1.6491, -1.9258, +1.1482 | Not triggered | PASS |
| `test_benchmark_diwire_async_collection[4-sync]` | -0.9659 | -0.9659, -5.4159, -0.8968 | Not triggered | PASS |
| `test_benchmark_diwire_async_collection[4-async]` | -0.6552 | +2.4850, -0.7598, -0.6552 | Not triggered | PASS |
| `test_benchmark_diwire_async_collection[16-sync]` | -0.7198 | -0.7198, -4.0796, +0.4260 | Not triggered | PASS |
| `test_benchmark_diwire_async_collection[16-async]` | +1.2072 | +1.7558, -1.5113, +1.2072 | Not triggered | PASS |
| `test_benchmark_diwire_late_cleanup_registration` | +0.5715 | -0.4157, +0.8205, +0.5715 | Not triggered | PASS |
| `test_benchmark_diwire_cold_compile[16]` | -0.2286 | -0.6618, +2.7845, -0.2286 | Not triggered | PASS |
| `test_benchmark_diwire_cold_compile[64]` | -0.6945 | -0.6945, +0.7768, -2.8995 | Not triggered | PASS |
| `test_benchmark_diwire_cold_compile[256]` | +0.9345 | -0.2781, +0.9345, +1.0052 | Not triggered | PASS |

| Confirmation | All 7 paired gains % | Positive | Bootstrap 95% interval % |
| --- | --- | ---: | --- |
| `test_benchmark_diwire_aresolve_scope_lifecycle[class]` | +2.1543, +5.3941, -5.8648, -0.5385, -2.6911, -5.2606, -0.6687 | 2/7 | -5.2606, +2.1543 |
| `test_benchmark_diwire_aresolve_dispatch_patterns[same_identity]` | +1.3410, +7.3511, -1.4308, -1.6672, -0.8737, -1.9510, +0.5820 | 3/7 | -1.6672, +1.3410 |

Class scope lifecycle confirmation interval remains [-5.260622%, +2.154292%], which includes slowdowns exceeding 2%. Its point estimate passes the declared rule; the experiment does not prove such slowdowns impossible. Original negative screens are retained.

## Memory and correctness

Five alternating fresh processes per variant, 100 warmup scopes and 1,000 traced scopes, GC before readings.

| Tracemalloc metric | Baseline samples bytes | Candidate samples bytes | Median base -> candidate | Increase | Allowance |
| --- | --- | --- | --- | ---: | ---: |
| retained_bytes | [4231, 4599, 4686, 4530, 7204] | [7463, 7862, 7463, 7548, 4680] | 4599 -> 7463 | 2864 | 8192 |
| peak_bytes | [11364, 11681, 11837, 11641, 14286] | [13737, 14080, 13737, 13766, 10899] | 11681 -> 13737 | 2056 | 8192 |

Both metrics pass max(2% baseline, 8 KiB). This measures Python traced allocations, not native allocations/RSS or long-running leak freedom.

- Baseline new public behavior contracts plus helper cases: 14 passed on macOS and Linux before optimization.
- Candidate focused contracts, existing transient contracts and compiler branches: 140 passed on macOS and Linux.
- Format unchanged; `make lint` passes Ruff, format check and strict mypy on macOS and Linux.
- `make test`: 1,373 passed, 105 skipped on each OS; 100% configured statement/branch coverage (4,114 statements, 1,528 branches).
- Frozen public API test passes; lock and API golden file unchanged.
- macOS CPython 3.10.17, GIL enabled: 14 focused contracts passed. CPython 3.14.3 free-threading, GIL disabled: 15 focused contracts/API cases passed. These are focused compatibility checks, not full cross-version suites.
- Final `COMPOSE_PROJECT_NAME=diwire-cached-leaf-20261028-final make test-e2e-fastapi`: 9 passed through separate Uvicorn/API and tests containers, including existing HTTP/WebSocket tests and new sequential/24-parallel request cache/cleanup checks. Both built image source/lock hashes read back and match candidate.
- Independent read-only semantic and measurement subagent reviews: no actionable findings. Auditor recomputed all 6 target, 39 broader and 2 confirmation cells from raw results; reviewed fairness and memory.

## Reproduction and artifacts

Raw archive uses the repository's existing `.agents/performance-evidence/` route. This archive is the only additional file beyond the seven implementation/test files and this report; it makes the full raw evidence available with the PR. No environments or containers committed.

[Raw JSON/logs, commands, hashes, reviews and study scripts](performance-evidence/2026-10-28/cached-async-leaf.json.gz).
Archive SHA-256: `263d89e125050c3f34a7e400731766ef51cbff4bd7c1a11ce35f3f950747e8a0`. Local unique study root: `/Users/roma/Documents/Codex/2026-10-28/let/work/diwire-study` (raw `evidence/` retained).

```sh
# Scripts and Dockerfile are included in the archive; full commands in commands.jsonl.
# Both checkouts at baseline, apply implementation.patch in documented split order.
# Isolated Linux container pinned with --cpuset-cpus=2; STUDY_ROOT mounted at same path.
sh "$STUDY_ROOT/linux_setup.sh"
/env/base/bin/python "$STUDY_ROOT/linux_calibrate.py"
cd "$STUDY_ROOT"
/env/base/bin/python run_pairs.py target 7
/env/base/bin/python analyze.py target 7
/env/base/bin/python run_pairs.py broad 3
/env/base/bin/python analyze.py broad 3
/env/base/bin/python prepare_confirmation.py
/env/base/bin/python run_pairs.py confirm 7
/env/base/bin/python analyze.py confirm 7
sh post_timing.sh
# Host candidate, after all source/test work:
COMPOSE_PROJECT_NAME=diwire-cached-leaf-20261028-final make test-e2e-fastapi
```

Linux runner sets `UV_PROJECT_ENVIRONMENT=/env/{variant}` to preserve host environments. A script-extraction SyntaxError before any formal timing was corrected; its log remains. Docker credential-helper setup failure and anonymous task-local configuration workaround are recorded. No timing sample was discarded, overwritten or pooled with earlier studies.
