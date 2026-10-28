from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Generator
from dataclasses import dataclass
from typing import cast

import pytest

from diwire import Container, Injected, Lifetime, LockMode, Scope, resolver_context
from diwire.exceptions import DIWireScopeMismatchError


@dataclass
class _Service:
    value: int


@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.ASYNC])
async def test_request_cache_reuses_value_and_delegates_to_owner(lock_mode: LockMode) -> None:
    calls = 0

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _Service(calls)

    container = Container(lock_mode=lock_mode, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    root = container.compile()
    try:
        with pytest.raises(DIWireScopeMismatchError):
            await root.aresolve(_Service)
        assert calls == 0
        async with root.enter_scope(Scope.REQUEST) as request:
            pending = request.aresolve(_Service)
            assert calls == 0
            first = await pending
            assert first is await request.aresolve(_Service)
            async with request.enter_scope(Scope.ACTION) as action:
                assert first is await action.aresolve(_Service)
        async with root.enter_scope(Scope.REQUEST) as request:
            second = await request.aresolve(_Service)
            assert second is not first
            assert second.value == 2
        assert calls == 2
    finally:
        await container.aclose()


async def test_async_lock_constructs_one_value_for_concurrent_requests_in_one_scope() -> None:
    calls = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return _Service(calls)

    container = Container(lock_mode=LockMode.ASYNC, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            tasks = [asyncio.create_task(request.aresolve(_Service)) for _ in range(16)]
            await asyncio.wait_for(entered.wait(), timeout=2)
            release.set()
            values = await asyncio.gather(*tasks)
            assert calls == 1
            assert all(value is values[0] for value in values)
    finally:
        await container.aclose()


@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.ASYNC])
async def test_failed_and_cancelled_construction_does_not_fill_request_cache(
    lock_mode: LockMode,
) -> None:
    calls = 0
    entered = asyncio.Event()
    error = LookupError("factory failed")

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        if calls == 2:
            entered.set()
            await asyncio.Event().wait()
        return _Service(calls)

    container = Container(lock_mode=lock_mode, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            before = asyncio.create_task(request.aresolve(_Service))
            before.cancel()
            with pytest.raises(asyncio.CancelledError):
                await before
            assert calls == 0
            with pytest.raises(LookupError) as caught:
                await request.aresolve(_Service)
            assert caught.value is error
            running = asyncio.create_task(request.aresolve(_Service))
            await asyncio.wait_for(entered.wait(), timeout=2)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            recovered = await request.aresolve(_Service)
            assert recovered.value == 3
            assert recovered is await request.aresolve(_Service)
            assert calls == 3
    finally:
        await container.aclose()


@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.ASYNC])
async def test_custom_awaitable_and_none_result_are_cached(lock_mode: LockMode) -> None:
    events: list[str] = []

    class _CustomAwaitable:
        def __await__(self) -> Generator[None, None, _Service]:
            events.append("await")
            yield from ()
            return _Service(7)

    def provide() -> Awaitable[_Service]:
        events.append("call")
        return _CustomAwaitable()

    async def provide_none() -> None:
        events.append("none")

    container = Container(lock_mode=lock_mode, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(
        provide_none, provides=bytes, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST
    )
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            first = await request.aresolve(_Service)
            assert first is await request.aresolve(_Service)
            assert await request.aresolve(bytes) is None
            assert await request.aresolve(bytes) is None
            assert events == ["call", "await", "none"]
    finally:
        await container.aclose()


async def test_invalid_awaitable_error_keeps_cache_empty() -> None:
    calls = 0

    def provide() -> Awaitable[_Service]:
        nonlocal calls
        calls += 1
        return cast("Awaitable[_Service]", _Service(0))

    container = Container(lock_mode=LockMode.ASYNC, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            for _ in range(2):
                with pytest.raises(TypeError, match="await"):
                    await request.aresolve(_Service)
            assert calls == 2
    finally:
        await container.aclose()


@pytest.mark.parametrize("wrapped", [False, True])
async def test_dependency_factory_and_inject_wrapper_keep_argument_resolution(
    *, wrapped: bool
) -> None:
    container = Container(lock_mode=LockMode.ASYNC, use_resolver_context=False)
    container.add_instance(17, provides=int)

    async def provide(value: int) -> _Service:
        return _Service(value)

    @resolver_context.inject
    async def injected(value: Injected[int]) -> _Service:
        return _Service(value)

    container.add_factory(
        injected if wrapped else provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST
    )
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            first = await request.aresolve(_Service)
            assert first.value == 17
            assert first is await request.aresolve(_Service)
    finally:
        await container.aclose()


async def test_zero_dependency_inject_wrapper_uses_internal_resolver() -> None:
    @resolver_context.inject
    async def provide() -> _Service:
        return _Service(23)

    container = Container(lock_mode=LockMode.ASYNC, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            first = await request.aresolve(_Service)
            assert first.value == 23
            assert first is await request.aresolve(_Service)
    finally:
        await container.aclose()


async def test_no_argument_factory_preserves_optional_default() -> None:
    marker = object()

    async def provide(value: object = marker) -> _Service:
        assert value is marker
        return _Service(29)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_factory(provide, dependencies={}, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            first = await request.aresolve(_Service)
            assert first.value == 29
            assert first is await request.aresolve(_Service)
    finally:
        await container.aclose()
