from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import make_dataclass
from typing import Any

import pytest

from diwire import Container, DependencyRegistrationPolicy, Lifetime, LockMode, MissingPolicy, Scope

_BATCH = 32


def make_graph(
    count: int, lock_mode: LockMode, *, suspending: bool = False
) -> tuple[Container, type[Any], list[int]]:
    container = Container(
        lock_mode=lock_mode,
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        use_resolver_context=False,
    )
    calls = [0]
    services = []

    def make_factory(service: type[Any]) -> Callable[[], Awaitable[Any]]:
        async def provide() -> Any:
            calls[0] += 1
            if suspending:
                await asyncio.sleep(0)
            return service()

        return provide

    for index in range(count):
        service = type(f"Leaf{index}", (), {})
        services.append(service)
        container.add_factory(
            make_factory(service),
            provides=service,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )
    root = make_dataclass("Root", [(f"leaf_{i}", cls) for i, cls in enumerate(services)])
    container.add(root, scope=Scope.REQUEST, lifetime=Lifetime.SCOPED)
    container.compile()
    return container, root, calls


def measure(
    benchmark: Any, batch: Callable[[], Awaitable[None]], loop: asyncio.AbstractEventLoop
) -> None:
    benchmark.extra_info["operations_per_batch"] = _BATCH
    benchmark.extra_info["boundaries"] = "compile/setup excluded; fresh scope and close included"
    benchmark.pedantic(
        lambda: loop.run_until_complete(batch()),
        iterations=60,
        rounds=7,
        warmup_rounds=2,
    )


@pytest.mark.parametrize("count", [1, 16])
@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.ASYNC])
def test_cached_async_leaf_scope(benchmark: Any, count: int, lock_mode: LockMode) -> None:
    container, root, calls = make_graph(count, lock_mode)
    resolver = container.compile()
    loop = asyncio.new_event_loop()

    async def check() -> None:
        async with resolver.enter_scope(Scope.REQUEST) as first_scope:
            first = await first_scope.aresolve(root)
            assert first is await first_scope.aresolve(root)
            assert calls[0] == count
        async with resolver.enter_scope(Scope.REQUEST) as second_scope:
            second = await second_scope.aresolve(root)
            assert second is not first
            assert second.leaf_0 is not first.leaf_0
        assert calls[0] == count * 2

    async def batch() -> None:
        for _ in range(_BATCH):
            async with resolver.enter_scope(Scope.REQUEST) as scope:
                await scope.aresolve(root)

    try:
        loop.run_until_complete(check())
        measure(benchmark, batch, loop)
    finally:
        loop.run_until_complete(container.aclose())
        loop.close()


def test_cached_async_leaf_suspending(benchmark: Any) -> None:
    container, root, _ = make_graph(16, LockMode.ASYNC, suspending=True)
    resolver = container.compile()
    loop = asyncio.new_event_loop()

    async def batch() -> None:
        for _ in range(_BATCH):
            async with resolver.enter_scope(Scope.REQUEST) as scope:
                await scope.aresolve(root)

    try:
        loop.run_until_complete(batch())
        measure(benchmark, batch, loop)
    finally:
        loop.run_until_complete(container.aclose())
        loop.close()


def test_cached_async_leaf_fastapi_asgi(benchmark: Any) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    container, root, calls = make_graph(16, LockMode.ASYNC)
    resolver = container.compile()
    app = FastAPI()

    @app.get("/work")
    async def work() -> dict[str, int]:
        async with resolver.enter_scope(Scope.REQUEST) as scope:
            value = await scope.aresolve(root)
            assert value is await scope.aresolve(root)
            return {"leaves": len(vars(value))}

    loop = asyncio.new_event_loop()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def batch() -> None:
        before = calls[0]
        for _ in range(_BATCH):
            response = await client.get("/work")
            assert response.status_code == 200
            assert response.json() == {"leaves": 16}
        assert calls[0] - before == _BATCH * 16

    try:
        loop.run_until_complete(batch())
        measure(benchmark, batch, loop)
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(container.aclose())
        loop.close()
