"""Measure real HTTP requests for the one-positional-call experiment.

Run each subject in a fresh process with its source directory first on PYTHONPATH.
This harness records samples. It does not decide whether a candidate passes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import uvicorn
from fastapi import FastAPI

from diwire import Container, Injected, Lifetime, LockMode, Scope, resolver_context
from tools.bb_perf_compare import fingerprint, runtime_metadata, verify_binding

if TYPE_CHECKING:
    from collections.abc import Iterator

REQUESTS = 30_000
WARMUP = 1_000
CONCURRENCY = 8


class Payload:
    """A transient async dependency."""


class Consumer:
    """A synchronous constructor with one async dependency."""

    def __init__(self, payload: Payload) -> None:
        self.payload = payload


class Resource:
    """A request resource with measured cleanup."""


async def payload() -> Payload:
    """Create one dependency without an artificial delay."""
    return Payload()


def make_container() -> Container:
    """Match the discovery graph and lock setting."""
    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(payload, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(Consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    return container


def make_app(subject: Path) -> FastAPI:
    """Build controls and the public injection workload."""
    container = make_container()
    lifecycle = {"opened": 0, "closed": 0}

    async def resource() -> AsyncGenerator[Resource, None]:
        lifecycle["opened"] += 1
        try:
            yield Resource()
        finally:
            lifecycle["closed"] += 1

    container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await container.aclose()
            logging.getLogger("uvicorn.error").info("DIWIRE_SOCKET_CLEAN_SHUTDOWN")

    app = FastAPI(lifespan=lifespan)

    @app.get("/control")
    async def control() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/consumer")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def consumer(value: Injected[Consumer]) -> dict[str, bool]:
        return {"ok": isinstance(value.payload, Payload)}

    @app.get("/resource")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def resource_route(value: Injected[Resource]) -> dict[str, bool]:
        return {"ok": isinstance(value, Resource)}

    @app.get("/status")
    def status() -> dict[str, object]:
        return {"lifecycle": lifecycle.copy(), "binding": verify_binding(subject)}

    return app


@contextmanager
def server(output: Path, subject: Path) -> Iterator[str]:
    """Pass an owned socket to one fresh server and retain its complete log."""
    with socket.socket() as listener, (output / "server.log").open("x") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(  # noqa: S603 - fixed module, inherited owned socket
            [
                sys.executable,
                "-m",
                "tests.performance.one_positional_socket",
                "--serve-fd",
                str(listener.fileno()),
                "--subject-root",
                str(subject),
            ],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        )
        try:
            yield address
        finally:
            process.send_signal(signal.SIGTERM)
            code: int | None = None
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise
            # Uvicorn restores and re-raises SIGTERM after graceful shutdown.
            if code not in (0, -signal.SIGTERM):
                msg = f"Socket server exit code: {code}"
                raise RuntimeError(msg)
    if "DIWIRE_SOCKET_CLEAN_SHUTDOWN" not in (output / "server.log").read_text():
        raise RuntimeError("Socket server did not confirm container shutdown")


async def requests(client: httpx.AsyncClient, route: str, count: int) -> dict[str, object]:
    """Retain every latency, error and body mismatch at fixed concurrency."""
    samples: list[float] = []
    errors: list[str] = []

    async def consume(indices: Iterator[int]) -> None:
        for _ in indices:
            start = time.perf_counter()
            try:
                response = await client.get(route)
                if response.status_code != 200 or response.content != b'{"ok":true}':
                    errors.append(f"{response.status_code}: {response.text}")
            except httpx.HTTPError as error:
                errors.append(repr(error))
            finally:
                samples.append(time.perf_counter() - start)

    start = time.perf_counter()
    await asyncio.gather(*(consume(iter(range(i, count, CONCURRENCY))) for i in range(CONCURRENCY)))
    elapsed = time.perf_counter() - start
    return {
        "count": len(samples),
        "seconds": elapsed,
        "requests_per_second": count / elapsed,
        "p95_seconds": sorted(samples)[math.ceil(0.95 * len(samples)) - 1],
        "latency_seconds": samples,
        "errors": errors,
    }


def inputs(subject: Path) -> dict[str, object]:
    """Read immutable inputs outside request timing."""
    return {
        "source_sha256": {
            name: digest
            for name, digest in fingerprint(subject / "src/diwire").items()
            if name.endswith(".py")
        },
        "runtime": runtime_metadata(),
        "binding": verify_binding(subject),
        "lock_sha256": hashlib.sha256((subject / "uv.lock").read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "requests": REQUESTS,
        "warmup": WARMUP,
        "concurrency": CONCURRENCY,
    }


async def probe(client: httpx.AsyncClient) -> bool:
    """Check server readiness outside request timing."""
    try:
        response = await client.get("/status")
    except httpx.ConnectError:
        return False
    response.raise_for_status()
    return True


async def wait_ready(client: httpx.AsyncClient) -> None:
    """Wait for server startup outside request timing."""
    for _ in range(200):
        if await probe(client):
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("Socket server did not become ready")


def save(output: Path, name: str, value: object) -> None:
    """Save evidence outside request timing."""
    with (output / name).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


async def measure_routes(output: Path, address: str, subject: Path) -> None:
    """Measure the same routes and counts in each fresh subject process."""
    result = inputs(subject)
    save(output, "inputs.json", result)
    async with httpx.AsyncClient(
        base_url=address, timeout=10, limits=httpx.Limits(max_connections=CONCURRENCY)
    ) as client:
        await wait_ready(client)
        for route in ("control", "consumer", "resource"):
            warmup = await requests(client, f"/{route}", WARMUP)
            measured = await requests(client, f"/{route}", REQUESTS)
            result[route] = {"warmup": warmup, "measured": measured}
            save(output, f"{route}.json", result[route])
            if warmup["errors"] or measured["errors"]:
                msg = f"Request errors for {route}"
                raise RuntimeError(msg)
        response = await client.get("/status")
        response.raise_for_status()
        result["server"] = response.json()
        expected = REQUESTS + WARMUP
        if response.json()["lifecycle"] != {"opened": expected, "closed": expected}:
            raise RuntimeError("Resource cleanup count differs from request count")
        if response.json()["binding"] != result["binding"]:
            raise RuntimeError("Server and client imported different DIWire sources")
    final = inputs(subject)
    result["final_inputs"] = final
    save(output, "result.json", result)
    if final != {key: result[key] for key in final}:
        raise RuntimeError("Socket inputs changed during measurement")


def main() -> None:
    """Run one subject or the private server process."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve-fd", type=int)
    mode.add_argument("--output", type=Path)
    parser.add_argument("--subject-root", type=Path, required=True)
    args = parser.parse_args()
    subject = args.subject_root.resolve()
    verify_binding(subject)
    if args.serve_fd is not None:
        uvicorn.run(
            make_app(subject),
            fd=args.serve_fd,
            workers=1,
            loop="asyncio",
            http="h11",
            access_log=False,
        )
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        with server(args.output, subject) as address:
            asyncio.run(measure_routes(args.output, address, subject))


if __name__ == "__main__":
    main()
