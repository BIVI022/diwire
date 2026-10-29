from __future__ import annotations

from collections.abc import Callable
from typing import cast

import typer

from diwire import Container, Lifetime
from diwire.exceptions import DIWireIntegrationError

try:
    from typer._click import globals as _typer_context
except ImportError:
    import click

    _get_current_context: Callable[[], object] = click.get_current_context
else:
    _get_current_context = _typer_context.get_current_context


def get_typer_context() -> typer.Context:
    try:
        return cast("typer.Context", _get_current_context())
    except RuntimeError as error:
        msg = "Typer context not available. Ensure the command runs inside a Typer application."
        raise DIWireIntegrationError(msg) from error


def add_typer_context(container: Container) -> None:
    container.add_factory(
        get_typer_context,
        provides=typer.Context,
        lifetime=Lifetime.TRANSIENT,
    )
