from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

import pytest

from diwire import All, Lifetime, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container

_BATCH_SIZE = 1_000


class Service:
    pass


@dataclass
class Consumer:
    services: tuple[Service, ...]


async def provide_service() -> Service:
    return Service()


async def provide_suspending_service() -> Service:
    await asyncio.sleep(0)
    return Service()


async def provide_consumer(services: All[Service]) -> Consumer:
    return Consumer(services)


@pytest.mark.parametrize("provider_kind", ["sync", "async", "mixed", "suspending"])
@pytest.mark.parametrize("dependency_count", [4, 16])
def test_benchmark_diwire_async_collection(
    benchmark: Any,
    provider_kind: Literal["sync", "async", "mixed", "suspending"],
    dependency_count: int,
) -> None:
    """Measure async resolution of a consumer and its transient components.

    Args:
        benchmark: Benchmark fixture.
        provider_kind: Component provider execution mode.
        dependency_count: Number of component providers collected for each consumer.

    """
    container = make_diwire_benchmark_container()
    for index in range(dependency_count):
        if provider_kind == "sync" or (provider_kind == "mixed" and index % 2 == 0):
            container.add(Service, component=index, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
        else:
            container.add_factory(
                provide_suspending_service if provider_kind == "suspending" else provide_service,
                component=index,
                lifetime=Lifetime.TRANSIENT,
                scope=Scope.APP,
            )
    container.add_factory(provide_consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    resolver = container.compile()
    loop = asyncio.new_event_loop()

    async def check() -> None:
        first = await resolver.aresolve(Consumer)
        second = await resolver.aresolve(Consumer)
        assert first is not second
        assert len(first.services) == len(second.services) == dependency_count
        assert len({id(service) for service in first.services}) == dependency_count
        assert len({id(service) for service in second.services}) == dependency_count
        for left, right in zip(first.services, second.services, strict=True):
            assert isinstance(left, Service)
            assert isinstance(right, Service)
            assert left is not right

    async def batch() -> None:
        for _ in range(_BATCH_SIZE):
            await resolver.aresolve(Consumer)

    def run_batch() -> None:
        loop.run_until_complete(batch())

    benchmark.extra_info.update(
        operations_per_batch=_BATCH_SIZE,
        dependency_count=dependency_count,
        provider_kind=provider_kind,
        operation="public aresolve consumer with All[Service]; compile and loop creation excluded",
    )
    try:
        loop.run_until_complete(check())
        benchmark.pedantic(run_batch, iterations=1, rounds=20, warmup_rounds=3)
        loop.run_until_complete(check())
    finally:
        loop.run_until_complete(resolver.aclose())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
