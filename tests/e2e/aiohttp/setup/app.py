from collections.abc import Awaitable, Callable
from typing import cast

from aiohttp import WSMsgType, web

from diwire import Container, Injected, Scope, resolver_context
from diwire.integrations.aiohttp import add_request_context, request_context_middleware
from tests.e2e.aiohttp.setup.config import AioHttpE2ESettings
from tests.e2e.aiohttp.setup.services import (
    CMService,
    RequestBasedService,
    WebSocketBasedService,
    latest_cleanup_path,
)
from tests.e2e.runtime import assert_free_threaded_runtime

app = web.Application(middlewares=[request_context_middleware])


async def health(_request: web.Request) -> web.StreamResponse:
    return web.Response(text="OK")


@resolver_context.inject(scope=Scope.REQUEST)
async def request_based_service(
    request: web.Request,
    service: Injected[RequestBasedService],
) -> web.StreamResponse:
    return web.Response(text=service.work())


@resolver_context.inject(scope=Scope.REQUEST)
async def cm_service(
    request: web.Request,
    service: Injected[CMService],
) -> web.StreamResponse:
    return web.Response(text=service.work())


async def cm_service_cleanup(_request: web.Request) -> web.StreamResponse:
    cleanup_path = latest_cleanup_path()
    return web.Response(text=f"Cleanup path: {cleanup_path}")


@resolver_context.inject(scope=Scope.REQUEST)
async def websocket_request_based_service(
    request: web.Request,
    service: Injected[WebSocketBasedService],
) -> web.StreamResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for message in ws:
        if message.type == WSMsgType.TEXT:
            await ws.send_str(service.work())
            break
    await ws.close()
    return ws


app.add_routes(
    [
        web.get("/health", health),
        web.get(
            "/services/request-based",
            cast(
                "Callable[[web.Request], Awaitable[web.StreamResponse]]",
                request_based_service,
            ),
        ),
        web.get(
            "/services/cm-service",
            cast(
                "Callable[[web.Request], Awaitable[web.StreamResponse]]",
                cm_service,
            ),
        ),
        web.get("/services/cm-service/cleanup", cm_service_cleanup),
        web.get(
            "/services/request-based-websocket",
            cast(
                "Callable[[web.Request], Awaitable[web.StreamResponse]]",
                websocket_request_based_service,
            ),
        ),
    ]
)


def main() -> None:
    assert_free_threaded_runtime()
    container = Container()
    add_request_context(container)
    container.add_context_manager(CMService, scope=Scope.REQUEST)

    settings = container.resolve(AioHttpE2ESettings)
    web.run_app(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
