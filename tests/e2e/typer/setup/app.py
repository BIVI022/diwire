from __future__ import annotations

import typer

from diwire import Container, Injected, Lifetime, Scope, resolver_context
from diwire.integrations.typer import add_typer_context
from tests.e2e.runtime import assert_free_threaded_runtime
from tests.e2e.typer.setup.services import ContextInfoService

app = typer.Typer()


container = Container()
add_typer_context(container)
container.add(
    ContextInfoService,
    scope=Scope.REQUEST,
    lifetime=Lifetime.SCOPED,
)


@app.command("context-direct")
@resolver_context.inject(scope=Scope.REQUEST)
def context_direct(
    ctx: typer.Context,
    resolved_ctx: Injected[typer.Context],
) -> None:
    info_name = resolved_ctx.info_name or "<missing>"
    same = "same" if resolved_ctx is ctx else "different"
    typer.echo(f"{info_name}:{same}")


@app.command("context-service")
@resolver_context.inject(scope=Scope.REQUEST)
def context_service(
    ctx: typer.Context,
    service: Injected[ContextInfoService],
) -> None:
    typer.echo(service.describe(ctx))


def main() -> None:
    assert_free_threaded_runtime()
    app()


if __name__ == "__main__":
    main()
