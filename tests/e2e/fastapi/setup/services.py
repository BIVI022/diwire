import asyncio
from dataclasses import dataclass
from types import TracebackType
from uuid import uuid4

from starlette.datastructures import State
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing_extensions import Self


class CustomState(State):
    pass


@dataclass
class RequestBasedService:
    request: Request

    def work(self) -> str:
        return f"Request path: {self.request.url.path}"


@dataclass
class RequestWithCustomStateService:
    request: Request[CustomState]

    def work(self) -> str:
        return f"Custom state value: {self.request.url.path}"


@dataclass
class WebSocketBasedService:
    websocket: WebSocket

    def work(self) -> str:
        return f"WebSocket path: {self.websocket.url.path}"


@dataclass
class CMService:
    def work(self) -> str:
        return "CMService working"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        print("CMService __exit__")


@dataclass
class AsyncLeafService:
    token: str


async def provide_async_leaf_service() -> AsyncLeafService:
    await asyncio.sleep(0)
    return AsyncLeafService(token=str(uuid4()))
