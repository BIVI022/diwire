"""Public request-scope graphs shared by the frozen public and socket workloads."""

from __future__ import annotations

from dataclasses import dataclass, make_dataclass
from typing import Any

from diwire import (
    Container,
    DependencyRegistrationPolicy,
    Lifetime,
    LockMode,
    MissingPolicy,
    ResolverContext,
    Scope,
)


class Leaf:
    pass


@dataclass
class Result:
    dependency: Any


async def _leaf() -> Leaf:
    return Leaf()


def _async_layer(result_type: type[Any], dependency_type: type[Any]) -> Any:
    async def layer(dependency: Any) -> Any:
        return result_type(dependency)

    layer.__annotations__ = {"dependency": dependency_type, "return": result_type}
    return layer


def build_graph(
    edges: int, *, all_async: bool = False
) -> tuple[Any, ResolverContext, tuple[type[Any], ...]]:
    context = ResolverContext()
    container = Container(
        lock_mode=LockMode.NONE,
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        resolver_context=context,
        use_resolver_context=True,
    )
    container.add_factory(_leaf, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    inner: type[Any] = Leaf
    layers = []
    for index in range(edges - 1):
        outer = make_dataclass(f"Layer{index}", [("dependency", inner)])
        layers.append(outer)
        if all_async:
            container.add_factory(
                _async_layer(outer, inner),
                provides=outer,
                lifetime=Lifetime.TRANSIENT,
                scope=Scope.REQUEST,
            )
        else:
            container.add(outer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
        inner = outer
    container.add_factory(
        _async_layer(Result, inner),
        provides=Result,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    return container.compile(), context, tuple(layers)


async def check_graph(resolver: Any, layers: tuple[type[Any], ...]) -> None:
    async with resolver.enter_scope(Scope.REQUEST) as scope:
        first = await scope.aresolve(Result)
        second = await scope.aresolve(Result)
        assert isinstance(first, Result)
        assert first is not second
        left, right = first.dependency, second.dependency
        for layer in reversed(layers):
            assert type(left) is type(right) is layer
            assert left is not right
            left, right = left.dependency, right.dependency
        assert isinstance(left, Leaf)
        assert isinstance(right, Leaf)
        assert left is not right
