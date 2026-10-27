# Direct async dependency-plan experiment

This plan prepares one local candidate. It does not establish a speed gain.
Do not open a PR until the later Linux comparison passes every gate.

## Hypothesis and scope

Base: `2dc938211a2cfb82b89323d025ac434c6dd246d1`, fetched main on 27 October 2026.
The outer `_resolve_dependency_value_async` function creates `_run` and three closure
cells for every edge. Its only production caller awaits it directly. Change only
that helper to `async def` with the same nested body. Add no cache, task, state,
dependency, or suspension point. The private coroutine name and traceback frame can
change. Public signatures must remain unchanged.

Discovery profiles contain 15,000 and 51,000 outer calls per 3,000 public resolutions.
Outer self time is 3.963% and 4.457% for mixed graphs with 5 and 17 edges. The larger
FastAPI ASGI profile reports 1.078%. These locate cost. They do not predict a gain.
The discovery evidence is in BB thread storage under
`thr_sr2vez8yyg/daily-discovery-2026-10-27-227d54dce7/findings.md`.

## Frozen inputs and cell inventory

Commit harness, inventory, and protocol before runtime edits. Keep runtime and
behavior tests in a later checkpoint. The comparison driver overlays the candidate
harness on both subjects, so both roles use identical setup and lifecycle code.
Use the full baseline and candidate SHAs, CPython 3.14.7 with the GIL on Linux amd64,
`uv sync --locked --python 3.14.7 --group dev --group docs`, and unchanged `uv.lock`.
Retain lock, interpreter, distribution, source, controller, and per-file harness hashes.
The driver records these, plus source import bindings before and after each process.
Check child server and client bindings against their controller as well.

`inventory.json` contains all 56 unique cells: 17 canonical DIWire cells, all 32
existing performance cells, 4 added public graphs, and 3 socket HTTP routes. No cell
is chosen after timing. Each cohort uses schema 1 from `tools/bb_perf_compare.py`:

| Order | Protocol | Cells | Process timeout | Full measurement budget |
| --- | --- | ---: | ---: | ---: |
| 1 | public.json | 21 | 180 s | 4,200 s |
| 2 | extended-a.json | 18 | 180 s | 4,200 s |
| 3 | extended-b.json | 18 | 180 s | 4,200 s |
| 4 | http.json | 3 | 180 s | 4,200 s |

Both mixed public targets repeat in the extended cohorts to satisfy the driver
schema. Each repeat is binding. Each cohort must pass. Cohorts run serially once,
in this order. Stop on the first failure. Retain earlier and partial results.
Before timing, verify that no CPU-heavy review, test, or unrelated work is running.
Record CPU topology, affinity, governor, quota, power state, load, and process list.
Use the same available CPU set for every process. Do not change affinity between roles.
The complete campaign budget is 16,800 s for cohorts plus 4,200 s for auxiliary probes.
A timeout is incomplete evidence, not a pass. There is no unchanged-source retry.

Public graphs use one immediate async leaf, 4 or 16 ordinary sync constructors, and
an async root adapter. Every operation enters and exits public request scope.
Compile, type/shape checks, and transient identity checks are outside timing.
All-async versions use the same types and scope boundary. Each public round resolves
10,000 graphs; use 3 warmup rounds and 7 retained rounds, one batch per round.
Existing cells keep their committed batch, warmup, and round settings.

## Decision rules and rationale

Require more than 3% throughput gain on each mixed public graph to justify a runtime change on both the representative small graph and the scaling graph.

Require more than 1% socket HTTP throughput gain on the 17-edge graph as the minimum useful application contribution for this one-helper change.

Use 3 fresh baseline calibration processes and 9 fresh alternating AB/BA pairs per
cohort. Every round and process remains in evidence. A process statistic is the
median of all retained rounds. A target median paired gain must exceed both its
practical floor and the greater calibration/baseline spread. The full range of
paired gains must be above zero. At 9 pairs this range has nominal 99.609375%
coverage for the median under independent pairs; serial drift can break that premise.

Stop as inconclusive if any calibration, baseline, or candidate process-median
spread exceeds 2%. Spread is `(max - min) / median`. The local discovery spread of
7.380% to 32.082% rules out local acceptance. Linux is the declared environment change.
No local comparison will be used to relax a rule or select a cohort.

Every protected paired time regression must be at most 2%. An interval that crosses
that limit is inconclusive. A target below its floor, wholly nonpositive effect, or
a protected regression wholly above tolerance rejects the candidate, subject to the
driver's stability checks. No aggregate can override a cell. Do not remove outliers,
widen limits, replace targets, or run a second unchanged-source attempt.
These useful-effect floors and protection limits come from discovery and the owner
contract, not from candidate timings. One candidate is allowed. End the campaign
on a semantic failure, rejected result, or unstable measurement environment.

## Socket HTTP contract

Use the same harness and loopback TCP endpoint for both roles. The OS selects an
unused port outside timing. Server and client are separate persistent spawn
processes. Each is pinned to one distinct CPU from the initial available set.
One Uvicorn worker uses asyncio and h11, no access log or lifespan hook.
FastAPI routes use `ResolverContext.inject(scope=Scope.REQUEST)` for 5-edge and
17-edge mixed graphs. `/plain` has the same response without injection.
Graph shape and transient identity are checked in the server before it starts.
Server startup, readiness, compilation, shutdown, and 1,024 route warmup requests
are outside timed requests. Close both compiled roots on server shutdown.

One aiohttp client process uses 16 persistent connections, 15 s request timeout,
and closed-loop load with 512 sequential requests per connection, 8,192 per batch.
Run 3 warmup batches then 7 retained batches per cell. All are saved. Each response
must be HTTP 200 with exact bytes `{"value":7}`. Any error fails the process.
The controller times one run command and a small completion reply, so fixed local
IPC cost is included for both roles. CPU probes, sorting, and latency transfer run
in setup/teardown outside that timer. The campaign also checks throughput from the
client request elapsed interval with the same target and protection rules. Client request timing excludes that IPC and server CPU probes.
Store every request latency, completed count, offered count, completed throughput,
mean and nearest-rank p95 latency, and client/server CPU fractions for every batch.
Offered load is closed-loop concurrency 16, not an independent constant arrival rate.

Require zero HTTP errors. In every batch, client process CPU/wall must be below
70% on its dedicated CPU and server CPU/wall above 80% on its dedicated CPU.
These checks require spare client capacity and a busy server. If either fails,
stop as inconclusive. Do not increase concurrency or add client capacity after
seeing results. Protect smaller HTTP and plain route throughput within 2%.
For all three routes, also apply the 2% paired regression limit to mean and p95
latency. Analyze their 7 retained batch medians per process with the same 3/9
calibration, spread, and full paired-range rules as protected time cells.
Latency and capacity checks are mandatory additional gates; the throughput driver's
`accepted` result alone is not whole-campaign acceptance. Warmup samples stay in raw
JSON but are not process statistics. The first 3 samples are warmup batches.

## Auxiliary startup and memory contract

Use the frozen subject directories exported by the driver, with each role's `src`
and harness on PYTHONPATH. Use the same executable, dependencies, hash seed 0,
`PYTHONDONTWRITEBYTECODE=1`, and disabled bytecode writes for both roles. Verify
source hashes in every probe result. Do not import an installed or other checkout.

Run all five scenarios from `tests/performance/startup_probe.py`: import, explicit,
autoregister, settings_first, and diwire_first. For each scenario use 3 fresh
baseline calibration probes and 9 alternating fresh-process pairs, once. Retain
all timing fields. Apply the same spread and protected 2% rules to `total_ns`
for every scenario. Other phase timers are diagnostic; near-zero timer overhead
must not become a separate acceptance ratio.

Run `python -m tests.performance.measure_compile_memory --output UNIQUE.json` in
3 fresh baseline calibration processes and 9 alternating fresh-process pairs.
The script measures compile retained and peak bytes for 16, 64, and 256 providers.
Keep every result. Each count and each metric is a separate protected cell.
Also run `python -m tests.performance.dependency_plan_memory --edges 5 --output UNIQUE.json`
and the same command with `--edges 17`. These measure the public mixed graphs: collect GC, start
tracemalloc(1), build/compile, run 100 warmup and 10,000 request-scope resolutions,
collect GC with the root retained, then record retained and peak bytes before
closing the root. Use 3 baseline and 9 alternating pairs of fresh processes,
one graph per process. Retain the graph, scope, and result identity checks outside
the allocation window. Store source, lock, and harness hashes with every result.

For all positive retained/peak memory metrics use the same 2% process spread ceiling
and require every paired increase at most 2%. Negative or zero denominators require
an inconclusive result. Use separate runs for timing and allocation tracing.
Canonical and generic cold compile timings are already in the extended cohorts.
Run auxiliary probes after the cohorts, serially, within 4,200 s total. No subset
may be accepted. Auxiliary analysis must retain complete input arrays and ratios.

## Correctness and later delivery gates

Guard every plan kind, deferred reads and error timing/identity, lookup order,
omitted/default/literal arguments, ordered and empty collections, provider handles,
sync awaitable values, cancellation, cleanup, cache identity, locks, and concurrent
request scopes. Run focused compiler/runtime and API-signature tests on the baseline
with new guards, then on the candidate. Reject a semantic failure immediately.

Run `make lint` and `make test`, require 100% configured coverage and unchanged
public API snapshot. Obtain independent semantic and measurement reviews. Require
exact-head supported Python and free-threaded CI before later acceptance.
Run `make test-e2e-fastapi` as the final implementation verification with a unique
`COMPOSE_PROJECT_NAME`. Report local limits. PR #298 stays a separate release blocker.

For a later Linux run, use the executable campaign runner. It calls all four
protocols, checks HTTP elapsed time, latency and capacity, then runs and checks
every auxiliary probe. A cohort decision alone cannot accept the campaign.
It keeps each process result, command, environment snapshot, and analysis in its
unique output directory. The campaign decision is `campaign-decision.json`.

```sh
uv run --locked python -m tests.performance.dependency_plan_campaign \
  --candidate-sha FULL_CANDIDATE_SHA --output /tmp/UNIQUE-campaign
```

Replace FULL_CANDIDATE_SHA with the local candidate checkpoint.
The following shows one driver call for inspection only. The campaign runner
owns the official fixed sequence; do not run the same cohort twice.
Use one unique output directory for every protocol:

```sh
uv run --locked python -m tools.bb_perf_compare \
  --base-sha 2dc938211a2cfb82b89323d025ac434c6dd246d1 \
  --candidate-sha FULL_CANDIDATE_SHA \
  --protocol plans/2026-10-27-async-dependency-plan/public.json \
  --output /tmp/UNIQUE-public
```

The campaign runner calls extended-a.json, extended-b.json, and http.json in order.
Do not dispatch a Linux timing run or open a PR in the local implementation stage.
