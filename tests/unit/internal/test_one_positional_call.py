from __future__ import annotations

import inspect

import pytest

from diwire._internal.injection import INJECT_RESOLVER_KWARG
from diwire._internal.resolvers.assembly import compiler


@pytest.mark.parametrize(
    ("parts", "positional", "keywords"),
    [
        ([], (), {}),
        ([compiler._ArgumentPart(kind="arg", value=1)], (1,), {}),
        (
            [
                compiler._ArgumentPart(kind="arg", value=1),
                compiler._ArgumentPart(kind="arg", value=2),
            ],
            (1, 2),
            {},
        ),
        ([compiler._ArgumentPart(kind="kw", name="value", value=1)], (), {"value": 1}),
        ([compiler._ArgumentPart(kind="star", value=iter((1, 2)))], (1, 2), {}),
        ([compiler._ArgumentPart(kind="starstar", value={"value": 1})], (), {"value": 1}),
        ([compiler._ArgumentPart(kind="star", value=())], (), {}),
        ([compiler._ArgumentPart(kind="starstar", value={})], (), {}),
    ],
)
def test_call_preserves_argument_kinds_and_order(
    parts: list[compiler._ArgumentPart],
    positional: tuple[int, ...],
    keywords: dict[str, int],
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def provider(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return result

    result = object()
    assert compiler._call_provider(callable_obj=provider, argument_parts=parts) is result
    assert calls == [(positional, keywords)]


def test_single_positional_preserves_callable_and_value_identity() -> None:
    value = object()

    class Consumer:
        def __init__(self, dependency: object, /) -> None:
            self.dependency = dependency

    class Factory:
        def __call__(self, dependency: object, /) -> object:
            return dependency

        def bound(self, dependency: object, /) -> object:
            return dependency

    factory = Factory()
    parts = [compiler._ArgumentPart(kind="arg", value=value)]
    assert compiler._call_provider(callable_obj=Consumer, argument_parts=parts).dependency is value
    for provider in (factory, factory.bound):
        assert compiler._call_provider(callable_obj=provider, argument_parts=parts) is value


@pytest.mark.asyncio
async def test_single_positional_returns_the_same_awaitable_without_running_it() -> None:
    value = object()
    calls: list[object] = []

    async def deferred() -> object:
        calls.append(value)
        return value

    coroutine = deferred()

    def provider(dependency: object) -> object:
        assert dependency is value
        return coroutine

    result = compiler._call_provider(
        callable_obj=provider, argument_parts=[compiler._ArgumentPart(kind="arg", value=value)]
    )
    assert result is coroutine
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CREATED
    assert calls == []
    assert await result is value
    assert calls == [value]


def test_single_positional_propagates_the_same_exception() -> None:
    error = ValueError("provider error")

    def provider(_dependency: object) -> object:
        raise error

    with pytest.raises(ValueError, match="provider error") as caught:
        compiler._call_provider(
            callable_obj=provider,
            argument_parts=[compiler._ArgumentPart(kind="arg", value=object())],
        )
    assert caught.value is error


def test_keyword_default_and_injection_resolver_keep_general_call() -> None:
    default = object()
    value = object()
    resolver = object()

    def provider(first: object = default, /, *, second: object) -> tuple[object, object]:
        return first, second

    assert compiler._call_provider(
        callable_obj=provider,
        argument_parts=[compiler._ArgumentPart(kind="kw", name="second", value=value)],
    ) == (default, value)

    calls: list[tuple[object, dict[str, object]]] = []

    def injected(dependency: object, **kwargs: object) -> None:
        calls.append((dependency, kwargs))

    parts = [compiler._ArgumentPart(kind="arg", value=value)]
    compiler._insert_internal_resolver_argument(argument_parts=parts, resolver=resolver)
    compiler._call_provider(callable_obj=injected, argument_parts=parts)
    assert calls == [(value, {INJECT_RESOLVER_KWARG: resolver})]


def test_star_expansion_and_keyword_errors_do_not_call_provider() -> None:
    calls: list[object] = []

    def provider(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    error = RuntimeError("expansion error")

    class Broken:
        def __iter__(self) -> Broken:
            raise error

    with pytest.raises(RuntimeError) as caught:
        compiler._call_provider(
            callable_obj=provider,
            argument_parts=[compiler._ArgumentPart(kind="star", value=Broken())],
        )
    assert caught.value is error
    with pytest.raises(TypeError, match="keywords must be strings"):
        compiler._call_provider(
            callable_obj=provider,
            argument_parts=[compiler._ArgumentPart(kind="starstar", value={1: object()})],
        )
    with pytest.raises(TypeError, match="duplicate keyword argument 'value'"):
        compiler._call_provider(
            callable_obj=provider,
            argument_parts=[
                compiler._ArgumentPart(kind="kw", name="value", value=object()),
                compiler._ArgumentPart(kind="starstar", value={"value": object()}),
            ],
        )
    assert calls == []
