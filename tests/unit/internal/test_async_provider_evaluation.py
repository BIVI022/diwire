from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from diwire._internal.resolvers.assembly import compiler
from diwire._internal.resolvers.assembly.planner import ProviderWorkflowPlan


def _workflow(*, is_async: bool) -> ProviderWorkflowPlan:
    return cast(
        "ProviderWorkflowPlan",
        SimpleNamespace(
            slot=1,
            provider_attribute="factory",
            dependency_plans=(),
            dependencies=(),
            provider_is_inject_wrapper=False,
            is_provider_async=is_async,
        ),
    )


@pytest.mark.asyncio
async def test_async_provider_reads_provider_only_when_awaited() -> None:
    calls: list[str] = []

    def original() -> str:
        calls.append("original")
        return "original"

    def replacement() -> str:
        calls.append("replacement")
        return "replacement"

    providers = {1: original}
    pending = compiler._build_local_value_async(
        runtime=cast("Any", SimpleNamespace(provider_by_slot=providers)),
        resolver=SimpleNamespace(),
        workflow=_workflow(is_async=False),
        provider_scope_resolver=SimpleNamespace(),
    )
    assert calls == []
    providers[1] = replacement
    assert await pending == "replacement"
    assert calls == ["replacement"]


@pytest.mark.asyncio
async def test_async_provider_keeps_sync_awaitable_result() -> None:
    calls: list[str] = []

    async def value() -> str:
        calls.append("awaited")
        return "value"

    expected = value()
    try:
        result = await compiler._build_local_value_async(
            runtime=cast("Any", SimpleNamespace(provider_by_slot={1: lambda: expected})),
            resolver=SimpleNamespace(),
            workflow=_workflow(is_async=False),
            provider_scope_resolver=SimpleNamespace(),
        )
        assert result is expected
        assert calls == []
        assert await result == "value"
    finally:
        expected.close()


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.asyncio
async def test_async_provider_preserves_exception(*, is_async: bool) -> None:
    error = LookupError("provider failed")

    def fail() -> None:
        raise error

    async def async_fail() -> None:
        fail()

    pending = compiler._build_local_value_async(
        runtime=cast(
            "Any", SimpleNamespace(provider_by_slot={1: async_fail if is_async else fail})
        ),
        resolver=SimpleNamespace(),
        workflow=_workflow(is_async=is_async),
        provider_scope_resolver=SimpleNamespace(),
    )
    with pytest.raises(LookupError) as caught:
        await pending
    assert caught.value is error


@pytest.mark.asyncio
async def test_async_provider_propagates_cancellation_and_cleanup() -> None:
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def provider() -> None:
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def resolve() -> None:
        await compiler._build_local_value_async(
            runtime=cast("Any", SimpleNamespace(provider_by_slot={1: provider})),
            resolver=SimpleNamespace(),
            workflow=_workflow(is_async=True),
            provider_scope_resolver=SimpleNamespace(),
        )

    task = asyncio.create_task(resolve())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
