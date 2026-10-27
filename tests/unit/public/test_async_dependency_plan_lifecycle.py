from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from diwire import Container, Lifetime, LockMode, Scope


class _Resource:
    pass


@dataclass
class _Managed:
    resource: _Resource


@dataclass
class _Consumer:
    managed: _Managed


@dataclass
class _Root:
    consumer: _Consumer


@pytest.mark.asyncio
async def test_cancellation_in_dependency_preserves_cleanup_and_allows_next_scope() -> None:
    events: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    container = Container(lock_mode=LockMode.ASYNC)

    async def resource() -> AsyncGenerator[_Resource, None]:
        events.append("resource:open")
        try:
            yield _Resource()
        finally:
            events.append("resource:close")

    @asynccontextmanager
    async def managed(resource: _Resource) -> AsyncGenerator[_Managed, None]:
        events.append("managed:open")
        try:
            yield _Managed(resource)
        finally:
            events.append("managed:close")

    async def consumer(managed: _Managed) -> _Consumer:
        entered.set()
        try:
            await release.wait()
        finally:
            events.append("consumer:exit")
        return _Consumer(managed)

    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_context_manager(managed, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_Root, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    resolver = container.compile()

    async def resolve() -> _Root:
        async with resolver.enter_scope(Scope.REQUEST) as request:
            return await request.aresolve(_Root)

    try:
        task = asyncio.create_task(resolve())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel("cancel dependency")
        with pytest.raises(asyncio.CancelledError, match="cancel dependency"):
            await task
        assert events == [
            "resource:open",
            "managed:open",
            "consumer:exit",
            "managed:close",
            "resource:close",
        ]
        release.set()
        result = await resolve()
        assert isinstance(result.consumer.managed.resource, _Resource)
        assert events[-5:] == [
            "resource:open",
            "managed:open",
            "consumer:exit",
            "managed:close",
            "resource:close",
        ]
    finally:
        await resolver.aclose()


@pytest.mark.asyncio
async def test_concurrent_scopes_keep_dependency_cache_and_async_lock_identity() -> None:
    opened: list[_Resource] = []
    closed: list[_Resource] = []
    ready = asyncio.Event()
    release = asyncio.Event()
    container = Container(lock_mode=LockMode.ASYNC)

    async def resource() -> AsyncGenerator[_Resource, None]:
        value = _Resource()
        opened.append(value)
        if len(opened) == 2:
            ready.set()
        await asyncio.sleep(0)
        try:
            yield value
        finally:
            closed.append(value)

    async def managed(resource: _Resource) -> _Managed:
        return _Managed(resource)

    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(managed, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    resolver = container.compile()

    async def in_scope() -> _Resource:
        async with resolver.enter_scope(Scope.REQUEST) as request:
            first, second = await asyncio.gather(
                request.aresolve(_Managed), request.aresolve(_Managed)
            )
            assert first is not second
            assert first.resource is second.resource
            await release.wait()
            return first.resource

    tasks = [asyncio.create_task(in_scope()) for _ in range(2)]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        release.set()
        left, right = await asyncio.gather(*tasks)
        assert left is not right
        assert len(opened) == len(closed) == 2
        assert set(opened) == set(closed)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await resolver.aclose()
