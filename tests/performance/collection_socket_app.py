"""Fixed socket subject for D20261029-01. No tracing during throughput runs."""

from __future__ import annotations

import asyncio
import gc
import statistics
import time
import tracemalloc
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from starlette.types import Message, Receive, Scope as ASGIScope, Send

import diwire
from diwire import All, Lifetime, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container

BATCH_SIZE = 2_048
COMPONENTS = 16
AMOUNT = 12_345
Mode = Literal["sync", "async", "mixed"]


@dataclass
class Rule:
    index: int

    def apply(self, amount: int) -> int:
        return amount * (100 + self.index) // 100


@dataclass
class Resource:
    sequence: int
    closed: bool = False

    def is_closed(self) -> bool:
        return self.closed


@dataclass
class Report:
    rules: tuple[Rule, ...]
    resource: Resource


async def provide_report(rules: All[Rule], resource: Resource) -> Report:
    return Report(rules, resource)


def rule_factory(index: int, mode: Mode) -> Callable[[], Rule] | Callable[[], Awaitable[Rule]]:
    def sync_rule() -> Rule:
        return Rule(index)

    async def async_rule() -> Rule:
        return Rule(index)

    return sync_rule if mode == "sync" or (mode == "mixed" and index % 2 == 0) else async_rule


class Meter:
    """Retain each batch's server window and complete per-request latency data."""

    def __init__(self) -> None:
        self.total_seconds = 0.0
        self.started = 0.0
        self.cpu_started = 0.0
        self.latencies: list[float] = []
        self.last: dict[str, object] = {}
        self.completed = 0
        self.received = 0

    def finish(self, started: float) -> None:
        now = time.perf_counter()
        self.latencies.append(now - started)
        self.completed += 1
        if len(self.latencies) == BATCH_SIZE:
            elapsed = now - self.started
            self.total_seconds += elapsed
            ordered = sorted(self.latencies)
            self.last = {
                "server_seconds": elapsed,
                "mean_seconds": statistics.mean(ordered),
                "p95_seconds": ordered[(95 * len(ordered) + 99) // 100 - 1],
                "latencies": self.latencies,
                "completed": self.completed,
                "server_cpu_seconds": time.process_time() - self.cpu_started,
            }
            self.latencies = []
            self.received = 0


async def probe_memory(resolve_report: Callable[[], Awaitable[dict[str, int]]]) -> dict[str, int]:
    # Separate from timed socket traffic. Keep all five fixed blocks.
    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(100):
            await resolve_report()
        gc.collect()
        tracemalloc.reset_peak()
        for _ in range(1_000):
            await resolve_report()
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
        return {"retained": retained, "peak": peak, "scopes": 1_000}
    finally:
        tracemalloc.stop()


def make_app(mode: Mode) -> FastAPI:
    container = make_diwire_benchmark_container()
    opened = 0
    closed = 0
    previous: Resource | None = None

    def resource() -> Generator[Resource, None, None]:
        nonlocal opened, closed, previous
        opened += 1
        value = Resource(opened)
        assert previous is not value
        previous = value
        try:
            yield value
        finally:
            value.closed = True
            closed += 1

    for index in range(COMPONENTS):
        container.add_factory(
            rule_factory(index, mode),
            provides=Rule,
            component=index,
            lifetime=Lifetime.TRANSIENT,
            scope=Scope.REQUEST,
        )
    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add_factory(provide_report, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    resolver = container.compile()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await resolver.aclose()

    app = FastAPI(lifespan=lifespan)
    meter = Meter()
    subject = str(Path(diwire.__file__).resolve())
    app.state.meter = meter

    async def resolve_report() -> dict[str, int]:
        async with resolver.enter_scope(Scope.REQUEST) as scope:
            report = await scope.aresolve(Report)
            assert isinstance(report.rules, tuple)
            assert tuple(rule.index for rule in report.rules) == tuple(range(COMPONENTS))
            assert len({id(rule) for rule in report.rules}) == COMPONENTS
            assert report.resource is await scope.aresolve(Resource)
            assert not report.resource.is_closed()
            result = {
                "request": report.resource.sequence,
                "components": len(report.rules),
                "total": sum(rule.apply(AMOUNT) for rule in report.rules),
            }
        assert report.resource.is_closed()
        return result

    app.get("/work")(resolve_report)

    @app.get("/stats")
    async def stats() -> dict[str, object]:
        return {
            "clock": meter.total_seconds,
            "batch": meter.last,
            "opened": opened,
            "closed": closed,
            "subject": subject,
        }

    @app.get("/memory")
    async def memory() -> dict[str, int]:
        return await probe_memory(resolve_report)

    return app


class SocketSubject:
    """Measure from the first request arrival to the final response body send."""

    def __init__(self, mode: Mode) -> None:
        self.app = make_app(mode)

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/work":
            await self.app(scope, receive, send)
            return
        meter: Meter = self.app.state.meter
        started = time.perf_counter()
        if not meter.received:
            meter.started = started
            meter.cpu_started = time.process_time()
        meter.received += 1

        async def measured_send(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                meter.finish(started)

        await self.app(scope, receive, measured_send)


async def serve(mode: Mode, descriptor: int) -> None:
    """Use the inherited bound socket. Do not race to reserve a free port."""
    import uvicorn

    config = uvicorn.Config(
        SocketSubject(mode),
        fd=descriptor,
        loop="asyncio",
        http="h11",
        lifespan="on",
        access_log=False,
        log_level="warning",
    )
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sync", "async", "mixed"))
    parser.add_argument("descriptor", type=int)
    arguments = parser.parse_args()
    asyncio.run(serve(arguments.mode, arguments.descriptor))
