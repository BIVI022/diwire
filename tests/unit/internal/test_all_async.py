"""Behavior of All dependencies inside an asynchronously resolved provider."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from dataclasses import dataclass

import pytest

from diwire import All, Container, Lifetime, LockMode, Scope
from diwire.exceptions import DIWireScopeMismatchError


@dataclass
class Member:
    name: str


@dataclass
class Consumer:
    members: tuple[Member, ...]


async def consumer(members: All[Member]) -> Consumer:
    return Consumer(members)


@pytest.mark.parametrize("count", [0, 1, 4])
async def test_async_consumer_preserves_sync_member_order_and_transient_identity(
    count: int,
) -> None:
    calls: list[str] = []
    container = Container()

    def factory(name: str) -> Callable[[], Member]:
        def provide() -> Member:
            calls.append(name)
            return Member(name)

        return provide

    for index in range(count):
        # The last registration has no component. It must still keep slot order.
        container.add_factory(
            factory(str(index)),
            provides=Member,
            component=index if index < count - 1 else None,
            lifetime=Lifetime.TRANSIENT,
        )
    container.add_factory(consumer, lifetime=Lifetime.TRANSIENT)
    try:
        first = await container.aresolve(Consumer)
        second = await container.aresolve(Consumer)
        names = [str(index) for index in range(count)]
        assert isinstance(first.members, tuple)
        assert [member.name for member in first.members] == names
        assert calls == names * 2
        assert all(
            left is not right for left, right in zip(first.members, second.members, strict=True)
        )
    finally:
        await container.aclose()


async def test_sync_member_with_suspending_dependency_stays_async_and_sequential() -> None:
    calls: list[str] = []
    container = Container()

    async def seed() -> int:
        calls.append("seed start")
        await asyncio.sleep(0)
        calls.append("seed end")
        return 7

    def dependent(value: int) -> Member:
        calls.append("sync dependent")
        return Member(str(value))

    async def last() -> Member:
        calls.append("async last")
        await asyncio.sleep(0)
        return Member("last")

    container.add_factory(seed)
    container.add_factory(dependent, component="dependent")
    container.add_factory(last, component="last")
    container.add_factory(consumer)
    try:
        result = await container.aresolve(Consumer)
        assert [member.name for member in result.members] == ["7", "last"]
        assert calls == ["seed start", "seed end", "sync dependent", "async last"]
    finally:
        await container.aclose()


def resource_factory(events: list[str], name: str) -> Callable[[], Generator[Member, None, None]]:
    def provide() -> Generator[Member, None, None]:
        events.append(f"{name} open")
        try:
            yield Member(name)
        finally:
            events.append(f"{name} close")

    return provide


@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.THREAD, LockMode.ASYNC])
async def test_mixed_collection_keeps_scope_ownership_cache_and_cleanup(
    lock_mode: LockMode,
) -> None:
    events: list[str] = []
    container = Container(lock_mode=lock_mode)

    async def async_member() -> AsyncGenerator[Member, None]:
        await asyncio.sleep(0)
        events.append("async open")
        try:
            yield Member("async")
        finally:
            events.append("async close")

    container.add_generator(resource_factory(events, "app"), component="app", scope=Scope.APP)
    container.add_generator(
        resource_factory(events, "request"), component="request", scope=Scope.REQUEST
    )
    container.add_generator(async_member, component="async", scope=Scope.REQUEST)
    container.add_factory(consumer, scope=Scope.REQUEST, lifetime=Lifetime.TRANSIENT)
    try:
        resolver = container.compile()
        with pytest.raises(DIWireScopeMismatchError):
            await resolver.aresolve(Consumer)
        async with resolver.enter_scope(Scope.REQUEST) as scope:
            if lock_mode is LockMode.ASYNC:
                first, second = await asyncio.gather(
                    scope.aresolve(Consumer), scope.aresolve(Consumer)
                )
            else:
                first = await scope.aresolve(Consumer)
                second = await scope.aresolve(Consumer)
            assert first is not second
            assert all(
                left is right for left, right in zip(first.members, second.members, strict=True)
            )
            assert events == ["app open", "request open", "async open"]
        expected_close = (
            ["async close", "request close"]
            if lock_mode is LockMode.THREAD
            else ["request close", "async close"]
        )
        assert events[-2:] == expected_close
        async with resolver.enter_scope(Scope.REQUEST) as scope:
            third = await scope.aresolve(Consumer)
            assert first.members[0] is third.members[0]
            assert first.members[1] is not third.members[1]
            assert first.members[2] is not third.members[2]
    finally:
        await container.aclose()
    assert events[-3:] == [*expected_close, "app close"]


@pytest.mark.parametrize("async_failure", [False, True])
async def test_collection_failure_stops_later_members_and_closes_earlier_resource(
    *,
    async_failure: bool,
) -> None:
    events: list[str] = []
    failure = RuntimeError("member failure")
    container = Container()

    def resource() -> Generator[Member, None, None]:
        events.append("open")
        try:
            yield Member("resource")
        finally:
            events.append("close")

    def fail() -> Member:
        events.append("fail")
        raise failure

    async def fail_async() -> Member:
        await asyncio.sleep(0)
        return fail()

    def later() -> Member:
        events.append("later")
        return Member("later")

    container.add_generator(resource, component="first", scope=Scope.REQUEST)
    container.add_factory(fail_async if async_failure else fail, component="fail")
    container.add_factory(later, component="later")
    container.add_factory(consumer, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as scope:
            with pytest.raises(RuntimeError) as caught:
                await scope.aresolve(Consumer)
            assert caught.value is failure
            assert events == ["open", "fail"]
        assert events == ["open", "fail", "close"]
    finally:
        await container.aclose()


async def test_cancellation_in_mixed_collection_stops_later_calls_and_cleans_up() -> None:
    events: list[str] = []
    started = asyncio.Event()
    container = Container()

    def resource() -> Generator[Member, None, None]:
        events.append("open")
        try:
            yield Member("resource")
        finally:
            events.append("close")

    async def wait() -> Member:
        events.append("wait")
        started.set()
        await asyncio.Event().wait()
        return Member("unreachable")

    def later() -> Member:
        events.append("later")
        return Member("later")

    container.add_generator(resource, component="first", scope=Scope.REQUEST)
    container.add_factory(wait, component="wait")
    container.add_factory(later, component="later")
    container.add_factory(consumer, scope=Scope.REQUEST)
    try:
        async with container.enter_scope(Scope.REQUEST) as scope:
            task = asyncio.create_task(scope.aresolve(Consumer))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert events == ["open", "wait"]
        assert events == ["open", "wait", "close"]
    finally:
        await container.aclose()


@dataclass
class AwaitableConsumer:
    values: tuple[Awaitable[Member], ...]


async def awaitable_consumer(values: All[Awaitable[Member]]) -> AwaitableConsumer:
    return AwaitableConsumer(values)


async def test_awaitable_returned_by_sync_member_remains_an_unawaited_value() -> None:
    future: asyncio.Future[Member] = asyncio.get_running_loop().create_future()
    container = Container()
    container.add_factory(lambda: future, provides=Awaitable[Member], component="future")
    container.add_factory(awaitable_consumer)
    try:
        result = await container.aresolve(AwaitableConsumer)
        assert result.values == (future,)
        assert result.values[0] is future
        assert not future.done()
    finally:
        future.cancel()
        await container.aclose()
