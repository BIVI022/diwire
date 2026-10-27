from __future__ import annotations

import asyncio
import platform
import time
from typing import Any

import pytest

from diwire import Scope
from tests.performance.dependency_plan_workload import Result, build_graph, check_graph


@pytest.mark.parametrize("edges", [5, 17])
@pytest.mark.parametrize("all_async", [False, True], ids=["mixed", "all_async"])
def test_benchmark_diwire_dependency_plan_public(
    benchmark: Any, edges: int, *, all_async: bool
) -> None:
    resolver, _context, layers = build_graph(edges, all_async=all_async)
    loop = asyncio.new_event_loop()

    async def batch() -> None:
        for _ in range(10_000):
            async with resolver.enter_scope(Scope.REQUEST) as request:
                await request.aresolve(Result)

    benchmark.extra_info.update(
        {"edges": edges, "all_async": all_async, "operations_per_batch": 10_000}
    )
    samples: list[dict[str, Any]] = []

    def run_batch() -> None:
        started = time.perf_counter()
        loop.run_until_complete(batch())
        samples.append(
            {
                "phase": "warmup" if len(samples) < 3 else "sample",
                "seconds": time.perf_counter() - started,
            }
        )

    try:
        loop.run_until_complete(check_graph(resolver, layers))
        benchmark.pedantic(run_batch, iterations=1, rounds=7, warmup_rounds=3)
        benchmark.extra_info["batches"] = samples
        loop.run_until_complete(check_graph(resolver, layers))
    finally:
        loop.run_until_complete(resolver.aclose())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@pytest.mark.parametrize("route", ["large", "small", "plain"])
def test_benchmark_diwire_dependency_plan_http(benchmark: Any, route: str) -> None:
    assert platform.system() == "Linux", (
        "Official socket cells require Linux; use module smoke on macOS"
    )
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    from tests.performance.dependency_plan_http import SocketWorkload

    workload = SocketWorkload()
    samples: list[dict[str, Any]] = []

    def setup() -> None:
        workload.prepare("/" + route, 8192)

    def teardown() -> None:
        samples.append(workload.collect() | {"phase": "warmup" if len(samples) < 3 else "sample"})

    try:
        initial_warmup = workload.batch("/" + route, 1024)
        benchmark.pedantic(
            workload.run, setup=setup, teardown=teardown, iterations=1, rounds=7, warmup_rounds=3
        )
        benchmark.extra_info.update(
            {
                "metadata": workload.metadata,
                "http_samples": samples,
                "initial_warmup": initial_warmup,
                "operations_per_batch": 8192,
            }
        )
        assert len(samples) == 10
        assert all(sample["requests"] == 8192 for sample in samples)
    finally:
        workload.close()
