from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("click")
pytest.importorskip("typer")

import click
import typer
from typer.main import get_command

import diwire._internal.integrations.typer as typer_integration
from diwire import Container
from diwire.exceptions import DIWireIntegrationError


@pytest.fixture()
def context() -> typer.Context:
    app = typer.Typer()

    @app.command()
    def command() -> None:
        pass

    return typer.Context(get_command(app), info_name="context-direct")


def test_get_typer_context_raises_when_context_is_missing() -> None:
    with pytest.raises(DIWireIntegrationError, match="Typer context not available"):
        typer_integration.get_typer_context()


def test_get_typer_context_returns_current_context(context: typer.Context) -> None:
    with context:
        resolved = typer_integration.get_typer_context()

    assert resolved is context


def test_add_typer_context_registers_factory_for_container_resolution(
    context: typer.Context,
) -> None:
    container = Container()
    typer_integration.add_typer_context(container)

    with context:
        resolved = container.resolve(typer.Context)

    assert resolved is context


def test_get_typer_context_uses_click_for_older_typer(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "typer._click", None)
        module = importlib.reload(typer_integration)

        with click.Context(click.Command("legacy"), info_name="legacy"):
            resolved = module.get_typer_context()

        assert resolved.info_name == "legacy"

    importlib.reload(typer_integration)


def test_get_typer_context_uses_typer_context_storage(
    monkeypatch: pytest.MonkeyPatch, context: typer.Context
) -> None:
    with monkeypatch.context() as patch:
        patch.setitem(
            sys.modules,
            "typer._click",
            SimpleNamespace(globals=SimpleNamespace(get_current_context=lambda: context)),
        )
        module = importlib.reload(typer_integration)

        assert module.get_typer_context() is context

    importlib.reload(typer_integration)
