from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Generator
from dataclasses import dataclass
from functools import partial
from typing import cast

import pytest

from diwire import Container, Lifetime, LockMode, Scope
from diwire.exceptions import DIWireScopeMismatchError


@dataclass
class _Service:
    value: int


class _ServiceAwaitable:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __await__(self) -> Generator[None, None, _Service]:
        self.events.append("await")
        yield from ()
        return _Service(7)


@pytest.mark.asyncio
async def test_transient_factory_work_starts_on_await_and_custom_awaitable_runs() -> None:
    events: list[str] = []

    def provide() -> Awaitable[_Service]:
        events.append("call")
        return _ServiceAwaitable(events)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    pending = container.aresolve(_Service)
    assert events == []
    try:
        first = await pending
        second = await container.aresolve(_Service)
        assert first.value == second.value == 7
        assert first is not second
        assert events == ["call", "await", "call", "await"]
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_transient_factory_cancellation_before_start_and_during_await() -> None:
    events: list[str] = []
    entered = asyncio.Event()

    async def provide() -> _Service:
        events.append("start")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("finally")
        return _Service(1)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    try:
        cancelled_before_start = asyncio.create_task(container.aresolve(_Service))
        cancelled_before_start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_before_start
        assert events == []
        running = asyncio.create_task(container.aresolve(_Service))
        await asyncio.wait_for(entered.wait(), timeout=2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert events == ["start", "finally"]
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_transient_partial_and_unannotated_optional_default_keep_call_shape() -> None:
    async def provide(value: int) -> _Service:
        return _Service(value)

    marker = object()

    async def optional(value: object = marker) -> _Service:
        assert value is marker
        return _Service(9)

    # Model a public callable with an unannotated optional parameter.
    optional.__annotations__.pop("value")
    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    try:
        container.add_factory(partial(provide, 7), provides=_Service, lifetime=Lifetime.TRANSIENT)
        assert (await container.aresolve(_Service)).value == 7
        container.add_factory(optional, provides=_Service, lifetime=Lifetime.TRANSIENT)
        assert (await container.aresolve(_Service)).value == 9
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_transient_factory_errors_and_public_replacement_remain_visible() -> None:
    def invalid() -> Awaitable[_Service]:
        # A false return annotation must retain the existing await-time error.
        return cast("Awaitable[_Service]", _Service(0))

    async def raising() -> _Service:
        message = "provider failed"
        raise ValueError(message)

    async def replacement() -> _Service:
        return _Service(11)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    try:
        container.add_factory(invalid, provides=_Service, lifetime=Lifetime.TRANSIENT)
        with pytest.raises(TypeError, match="await"):
            await container.aresolve(_Service)
        container.add_factory(raising, provides=_Service, lifetime=Lifetime.TRANSIENT)
        with pytest.raises(ValueError, match="provider failed"):
            await container.aresolve(_Service)
        container.add_factory(replacement, provides=_Service, lifetime=Lifetime.TRANSIENT)
        assert (await container.aresolve(_Service)).value == 11
    finally:
        await container.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.ASYNC])
async def test_cached_async_factory_retains_identity_and_locking(lock_mode: LockMode) -> None:
    calls = 0

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _Service(calls)

    container = Container(lock_mode=lock_mode, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.SCOPED, scope=Scope.APP)
    resolver = container.compile()
    try:
        if lock_mode is LockMode.ASYNC:
            values = await asyncio.gather(*(resolver.aresolve(_Service) for _ in range(24)))
        else:
            values = [await resolver.aresolve(_Service) for _ in range(2)]
        assert calls == 1
        assert all(value is values[0] for value in values)
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_request_scope_is_checked_before_factory_call() -> None:
    calls = 0

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        return _Service(calls)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    resolver = container.compile()
    try:
        with pytest.raises(DIWireScopeMismatchError):
            await resolver.aresolve(_Service)
        assert calls == 0
        async with container.enter_scope(Scope.REQUEST) as request:
            first = await request.aresolve(_Service)
            async with request.enter_scope(Scope.ACTION) as action:
                second = await action.aresolve(_Service)
            assert first.value == 1
            assert second.value == 2
            assert first is not second
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_provider_exception_identity_and_recovery_are_preserved() -> None:
    error = LookupError("same provider exception")
    calls = 0

    async def provide() -> _Service:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return _Service(calls)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_factory(provide, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    try:
        with pytest.raises(LookupError) as caught:
            await container.aresolve(_Service)
        assert caught.value is error
        assert (await container.aresolve(_Service)).value == 2
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_factory_with_dependency_still_receives_the_argument() -> None:
    async def provide(value: int) -> _Service:
        return _Service(value)

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_instance(17, provides=int)
    container.add_factory(provide, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    try:
        assert (await container.aresolve(_Service)).value == 17
    finally:
        await container.aclose()


@pytest.mark.asyncio
async def test_async_generator_cleanup_still_runs_after_scope_exit() -> None:
    events: list[str] = []

    async def provide() -> AsyncGenerator[_Service, None]:
        events.append("enter")
        try:
            yield _Service(23)
        finally:
            events.append("exit")

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(provide, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as request:
            assert (await request.aresolve(_Service)).value == 23
            assert events == ["enter"]
        assert events == ["enter", "exit"]
    finally:
        await container.aclose()
