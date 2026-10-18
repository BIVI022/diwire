from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from diwire._internal.resolvers.assembly import compiler


@pytest.mark.parametrize("requires_async", [False, True])
@pytest.mark.asyncio
async def test_async_slot_dependency_reads_method_only_when_awaited(
    *, requires_async: bool
) -> None:
    calls: list[str] = []

    def original() -> str:
        calls.append("original")
        return "original"

    async def async_original() -> str:
        return original()

    def replacement() -> str:
        calls.append("replacement")
        return "replacement"

    async def async_replacement() -> str:
        return replacement()

    resolver = SimpleNamespace(resolve_1=original, aresolve_1=async_original)
    pending = compiler._dependency_value_for_slot_async(
        resolver=resolver,
        dependency_workflow=cast("Any", SimpleNamespace(slot=1)),
        dependency_requires_async=requires_async,
    )
    assert calls == []
    resolver.resolve_1 = replacement
    resolver.aresolve_1 = async_replacement
    assert await pending == "replacement"
    assert calls == ["replacement"]


@pytest.mark.parametrize("requires_async", [False, True])
@pytest.mark.asyncio
async def test_async_slot_dependency_preserves_exception(*, requires_async: bool) -> None:
    error = LookupError("dependency failed")

    def fail() -> None:
        raise error

    async def async_fail() -> None:
        fail()

    pending = compiler._dependency_value_for_slot_async(
        resolver=SimpleNamespace(resolve_1=fail, aresolve_1=async_fail),
        dependency_workflow=cast("Any", SimpleNamespace(slot=1)),
        dependency_requires_async=requires_async,
    )
    with pytest.raises(LookupError) as caught:
        await pending
    assert caught.value is error


@pytest.mark.asyncio
async def test_async_slot_dependency_propagates_cancellation_and_cleanup() -> None:
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def dependency() -> None:
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def resolve() -> None:
        await compiler._dependency_value_for_slot_async(
            resolver=SimpleNamespace(aresolve_1=dependency),
            dependency_workflow=cast("Any", SimpleNamespace(slot=1)),
            dependency_requires_async=True,
        )

    task = asyncio.create_task(resolve())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
