# D20261029-01: synchronous members of an async collection

Status: preregistered. A local candidate is not an accepted performance result.

## Hypothesis and scope

The async All dependency loop awaits one helper coroutine for each synchronous
member. The helper only looks up and calls the synchronous slot. Call that slot
inside the deferred loop when the full workflow requires_async flag is false.
Keep workflow.slot, lookup timing, sequence and the awaited async-member helper.
Change no other runtime path. Do not use the sync helper's cache shortcuts.

Baseline: fetched main 23b7f02be327a4e10089f74a708cbb1e26f7c766.
Lock SHA-256: 93681b8ff611ef57632c4d2ace68b528ef7d02707bce39327a35a0422b6c6576.
The harness checkpoint precedes the runtime edit. Record both checkpoint and
candidate full SHAs in the BB evidence receipt before Linux dispatch. Compare
baseline library source with candidate library source under this same harness.
The comparator checks source import paths in every process. The socket harness
also checks the server import against the intended subject's src/diwire path.

## Practical effects and fixed decisions

A five percent gain for public All4 and All16 synchronous collections is needed to justify a new branch on each member. A two percent socket throughput gain is needed because HTTP, scope cleanup and response work dilute this cost.

The preceding sentence is the exact gain rationale in both schema-1 protocols.
These floors come from the job contract and cost dilution, not candidate timing.
The baseline cost probe counted 16,000 helper calls in 1,000 public All16
resolutions. Discovery's profiled self time is a cost signal, not a speed result.
No useful effect or noise estimate is inferred from profiler timings.

Run the two fixed protocols once on Ubuntu 24.04, CPython 3.14.7, locked dev/docs
dependencies, with no other checks or reviews consuming CPU. Each uses three
fresh baseline calibrations and five alternating AB/BA fresh-process pairs.
Retain all measured rounds, processes, environment, logs and outliers. Core
pytest-benchmark warmups are fixed by each cell (normally three), run before
measurement and excluded from the saved decision samples. The existing fixture
does not retain those warmup durations. Socket raw evidence also retains both
warmup batches. Do not treat core warmups as saved measured samples. No sample
selection, unchanged retry, threshold change, or focused timing recovery.
Each protocol has a 4,200-second total limit and a 600-second process limit.
Missing data or execution failure prevents acceptance. Noise or an uncertain
boundary produces an inconclusive receipt. Reject semantic or API failures.

For each target, median throughput gain must exceed its floor AND observed
baseline spread. Every target pair must improve. Check calibration, baseline and
candidate process spread against 3%. Every protected pair must stay within 2%
elapsed-time regression. Inspect each cell, not just the aggregate. Both protocol
decisions must pass. A core pass alone is insufficient. Do not average effects
between protocols. Existing comparator rules enforce these requirements.

Core has 31 cells: All4/All16 sync targets, all 17 canonical cells, All4/All16
async controls, mixed and suspending All16, a mixed graph, scope lifecycle with
and without cleanup, warm async request cache, cold compile at 64 and 256, and
plain/settings recursive registration. PR #298 remains a separate release
blocker. This campaign does not claim to clear that historical signal.

## Socket workload and clock

Use one fresh Uvicorn server per cell/process, asyncio loop, h11, no access log,
no tracing, and an inherited loopback listening socket. Use eight persistent
HTTP/1.1 connections from eight client threads. Each batch has 2,048 requests.
Keep seven measured batches and two warmup batches in each cell. Server startup,
compilation, client pool creation, statistics reads and memory probes are outside
timing. Each request resolves an async report with 16 ordered transient pricing
rules plus a scoped generator resource. Rules apply fixed integer rates 100..115
to amount 12,345. It validates tuple order and distinct transient identities,
resource cache identity, scope exit, response count, checksum and fresh resource
sequence. All resources must close. Each client validates every HTTP response.
Any error fails the process. Protect all-async and mixed-component socket cells.

The pytest-benchmark timer reads a cumulative clock supplied by the server.
It advances once per complete batch by the wall time from the first /work ASGI
arrival to the final response body send. The difference of two clock readings
is exactly that batch's server window. Client-side JSON checks and /stats calls
are outside the window after the final body. Network backpressure and gaps
between requests remain inside the window. This is a bounded closed-loop HTTP
workload, not a claim about production peak capacity. Inspect client saturation,
server CPU and the retained environment before acceptance. Inadequate saturation
or a client bottleneck makes the HTTP evidence inconclusive. Do not retune the
fixed workload after results. Save all per-request server and client durations for latency. Each measured
batch must show server process CPU / server window >= 0.75 and client process CPU
/ client wall time <= 0.85. This fixed conservative check needs an active server
and spare client CPU. It can reject a valid but client-limited load. Such a
result is inconclusive. Retain CPU/wall values for every warmup and measured
batch. Do not retune concurrency or discard a failing batch.

For every socket cell and pair, each pooled mean and p95 latency per process must
stay within 2% of baseline. Check both server and client latency. Mean and p95 use all requests in all seven measured
batches (warmups retained separately). Run five memory blocks per process after
socket timing. Each starts tracing, primes 100 request scopes, collects GC,
resets peak, runs 1,000 scopes, collects GC and records peak and retained traced
Python bytes. No tracing runs during throughput samples. Require each pair's
median peak and retained memory to stay within 2%. These are traced Python
allocations for the fixed scope workload, not whole-server RSS claims. Apply
socket_checks.py to the raw socket comparison directory as a required gate.
It also verifies all server windows, raw benchmark rounds and import metadata.
A missing or malformed metric is an error. A >2% increase is inconclusive and
prevents acceptance. Preserve all five memory blocks; do not discard GC tails.

## Commands and binding

After local checks and review, the root records the full candidate SHA and calls
the existing BB Linux performance comparison workflow twice, in this order:

1. protocol .bb/automation/protocols/d20261029-01/core.json
2. protocol .bb/automation/protocols/d20261029-01/socket.json

Both use base_sha=23b7f02be327a4e10089f74a708cbb1e26f7c766 and the exact local
candidate SHA, with quality_mode=true. The committed tools/bb_perf_compare.py
pins CPython 3.14.7, archives both subject sources and uses the candidate harness
for both. Retain uploaded complete or partial artifacts in unique BB paths.
Use unique COMPOSE_PROJECT_NAME for final E2E. Then run:

    uv run --locked python -m tests.performance.socket_checks SOCKET_COMPARISON_DIR

This worker does not dispatch Linux timing, push or open a PR. It prepares a
bounded, testable candidate only. No Linux acceptance result is claimed here.
Supported-Python CI and independent exact-head semantic/measurement review remain
required before acceptance. Run focused tests, make lint and make test with 100%
coverage and unchanged API signatures. Run make test-e2e-fastapi last. Preserve
all receipts and earlier attempts on their own branches. One mechanism only.

## Semantic constraints

Preserve ordered sequential calls, tuple and object identity, transient and
scoped caches, owner routing, locks, cleanup, first error and cancellation.
Keep async dependencies of synchronous providers on the async path. Awaitable
objects returned by synchronous providers remain values. Slot lookup and errors
stay deferred until awaiting. Do not change public API signatures, dependencies,
Python support or unrelated acceptance controls. Reject a real behavior failure.
