import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest

from diwire import Container, Lifetime, LockMode, Scope


class Token:
    pass


class Consumer:
    def __init__(self, token: Token, /) -> None:
        self.token = token


class Factory:
    def __call__(self, token: Token, /) -> Consumer:
        return Consumer(token)

    def bound(self, token: Token, /) -> Consumer:
        return Consumer(token)


async def async_consumer(token: Token, /) -> Consumer:
    await asyncio.sleep(0)
    return Consumer(token)


@pytest.mark.parametrize("kind", ["constructor", "async", "callable", "bound"])
@pytest.mark.parametrize("lock_mode", [LockMode.NONE, LockMode.THREAD, LockMode.ASYNC])
@pytest.mark.asyncio
async def test_one_dependency_preserves_lifetimes_order_and_cleanup(
    kind: str, lock_mode: LockMode
) -> None:
    events: list[str] = []
    created: list[Token] = []

    async def resource() -> AsyncGenerator[Token, None]:
        token = Token()
        created.append(token)
        events.append("open")
        try:
            yield token
        finally:
            events.append("close")

    container = Container(lock_mode=lock_mode)
    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    if kind == "constructor":
        container.add(Consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    else:
        factory = Factory()
        providers: dict[str, Callable[[Token], Consumer | Awaitable[Consumer]]] = {
            "async": async_consumer,
            "callable": factory,
            "bound": factory.bound,
        }
        provider = providers[kind]
        container.add_factory(
            provider, provides=Consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST
        )
    async with container:
        async with container.enter_scope(Scope.REQUEST) as scope:
            first = await scope.aresolve(Consumer)
            second = await scope.aresolve(Consumer)
            assert first is not second
            assert first.token is second.token is created[0]
            assert events == ["open"]
        assert events == ["open", "close"]
        async with container.enter_scope(Scope.REQUEST) as scope:
            third = await scope.aresolve(Consumer)
            assert third.token is created[1]
            assert third.token is not first.token
    assert events == ["open", "close", "open", "close"]


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.asyncio
async def test_one_dependency_preserves_provider_exception_and_cleanup(*, is_async: bool) -> None:
    error = ValueError("consumer failed")
    events: list[str] = []

    async def resource() -> AsyncGenerator[Token, None]:
        try:
            yield Token()
        finally:
            events.append("closed")

    def fail(token: Token, /) -> Consumer:
        assert isinstance(token, Token)
        raise error

    async def async_fail(token: Token, /) -> Consumer:
        await asyncio.sleep(0)
        return fail(token)

    container = Container()
    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(
        async_fail if is_async else fail,
        provides=Consumer,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    async with container:
        with pytest.raises(ValueError, match="consumer failed") as caught:
            async with container.enter_scope(Scope.REQUEST) as scope:
                await scope.aresolve(Consumer)
        assert caught.value is error
        assert events == ["closed"]


@pytest.mark.asyncio
async def test_one_dependency_cancellation_after_suspension_closes_resource() -> None:
    entered = asyncio.Event()
    blocked = asyncio.Event()
    events: list[str] = []

    async def resource() -> AsyncGenerator[Token, None]:
        try:
            yield Token()
        finally:
            events.append("closed")

    async def consumer(token: Token, /) -> Consumer:
        entered.set()
        try:
            await blocked.wait()
        finally:
            events.append("cancelled")
        return Consumer(token)

    container = Container()
    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    async with container:
        async with container.enter_scope(Scope.REQUEST) as scope:
            task = asyncio.create_task(scope.aresolve(Consumer))
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel("one positional cancellation")
            with pytest.raises(asyncio.CancelledError, match="one positional cancellation"):
                await task
            assert events == ["cancelled"]
        assert events == ["cancelled", "closed"]
