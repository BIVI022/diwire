from __future__ import annotations

import uvicorn
from litestar import Litestar, get, websocket
from litestar.connection import Request, WebSocket
from litestar.datastructures.state import State
from litestar.exceptions import WebSocketDisconnect

from diwire import Container, Injected, Scope, resolver_context
from diwire.integrations.litestar import RequestContextMiddleware, add_request_context
from tests.e2e.litestar.setup.config import LitestarE2ESettings
from tests.e2e.litestar.setup.services import (
    CMService,
    RequestBasedService,
    WebSocketBasedService,
    latest_cleanup_path,
)
from tests.e2e.runtime import assert_free_threaded_runtime

# diwire resolves dependencies via runtime type hints; populate module globals so
# forward references like `Request[object, object, State]` can be evaluated.
globals()["Request"] = Request
globals()["WebSocket"] = WebSocket
globals()["State"] = State


@get("/health")
async def health() -> str:
    return "OK"


@get("/services/request-based")
@resolver_context.inject(scope=Scope.REQUEST)
async def request_based_service(service: Injected[RequestBasedService]) -> str:
    return service.work()


@get("/services/cm-service")
@resolver_context.inject(scope=Scope.REQUEST)
async def cm_service(service: Injected[CMService]) -> str:
    return service.work()


@get("/services/cm-service/cleanup")
async def cm_service_cleanup() -> str:
    cleanup_path = latest_cleanup_path()
    return f"Cleanup path: {cleanup_path}"


@websocket("/services/request-based-websocket")
@resolver_context.inject(scope=Scope.REQUEST)
async def websocket_request_based_service(
    socket: WebSocket[object, object, State],
    service: Injected[WebSocketBasedService],
) -> None:
    await socket.accept()
    try:
        _ = await socket.receive_text()
    except WebSocketDisconnect:
        return
    await socket.send_text(service.work())
    await socket.close()


app = Litestar(
    route_handlers=[
        health,
        request_based_service,
        cm_service,
        cm_service_cleanup,
        websocket_request_based_service,
    ],
    middleware=[RequestContextMiddleware()],
)


def main() -> None:
    assert_free_threaded_runtime()
    container = Container()
    add_request_context(container)
    container.add_context_manager(CMService, scope=Scope.REQUEST)

    settings = container.resolve(LitestarE2ESettings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
