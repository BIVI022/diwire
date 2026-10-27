"""Use separate persistent server and client processes for each socket HTTP cell."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import statistics
import sys
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import aiohttp

import diwire
from diwire import Injected, Scope
from tests.performance.dependency_plan_workload import Result, build_graph, check_graph


def _pin(role: int) -> list[int]:
    set_affinity = getattr(os, "sched_setaffinity", None)
    if hasattr(os, "sched_getaffinity") and set_affinity is not None:
        cpus = sorted(os.sched_getaffinity(0))
        if len(cpus) < 2:
            raise RuntimeError("HTTP measurement requires two available CPUs")
        set_affinity(0, {cpus[role]})
        return [cpus[role]]
    return []


def _binding() -> dict[str, Any]:
    source = Path(diwire.__file__).resolve()
    compiler = source.parent / "_internal/resolvers/assembly/compiler.py"
    return {
        "diwire_file": str(source),
        "compiler_sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
    }


def _server(pipe: Connection) -> None:
    import socket

    import uvicorn
    from fastapi import FastAPI

    affinity = _pin(0)
    small, small_context, small_layers = build_graph(5)
    large, large_context, large_layers = build_graph(17)
    asyncio.run(check_graph(small, small_layers))
    asyncio.run(check_graph(large, large_layers))
    app = FastAPI()

    @app.get("/small")
    @small_context.inject(scope=Scope.REQUEST)
    async def small_route(result: Injected[Result]) -> dict[str, int]:
        return {"value": 7}

    @app.get("/large")
    @large_context.inject(scope=Scope.REQUEST)
    async def large_route(result: Injected[Result]) -> dict[str, int]:
        return {"value": 7}

    @app.get("/plain")
    async def plain_route() -> dict[str, int]:
        return {"value": 7}

    @app.get("/cpu")
    async def cpu_route() -> dict[str, float]:
        return {"seconds": time.process_time()}

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        pipe.send(
            {
                "port": port,
                "affinity": affinity,
                "binding": _binding(),
                "bytecode_writes_disabled": sys.dont_write_bytecode,
            }
        )
        try:
            uvicorn.Server(
                uvicorn.Config(
                    app,
                    loop="asyncio",
                    http="h11",
                    workers=1,
                    access_log=False,
                    log_level="error",
                    lifespan="off",
                    timeout_keep_alive=60,
                )
            ).run(sockets=[sock])
        finally:
            asyncio.run(small.aclose())
            asyncio.run(large.aclose())


async def _requests(session: aiohttp.ClientSession, url: str, count: int) -> list[float]:
    latencies = []
    for _ in range(count):
        started = time.perf_counter()
        async with session.get(url) as response:
            body = await response.read()
            if response.status != 200 or body != b'{"value":7}':
                msg = f"HTTP response failed: {response.status} {body!r}"
                raise RuntimeError(msg)
        latencies.append(time.perf_counter() - started)
    return latencies


async def _client_loop(pipe: Connection, port: int) -> None:
    base = f"http://127.0.0.1:{port}"
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=16),
        timeout=aiohttp.ClientTimeout(total=15),
    ) as session:
        for _ in range(200):
            try:
                async with session.get(base + "/cpu") as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientConnectorError:
                await asyncio.sleep(0.05)
        else:
            raise RuntimeError("HTTP server was not ready within ten seconds")
        pipe.send(
            {
                "ready": True,
                "binding": _binding(),
                "bytecode_writes_disabled": sys.dont_write_bytecode,
            }
        )
        while (command := pipe.recv()) is not None:
            route, count = command
            async with session.get(base + "/cpu") as response:
                before = (await response.json())["seconds"]
            pipe.send({"prepared": True})
            assert pipe.recv() == "run"
            cpu_started, started = time.process_time(), time.perf_counter()
            results = await asyncio.gather(
                *(_requests(session, base + route, count // 16) for _ in range(16))
            )
            elapsed = time.perf_counter() - started
            cpu_elapsed = time.process_time() - cpu_started
            pipe.send({"done": True})
            assert pipe.recv() == "collect"
            async with session.get(base + "/cpu") as response:
                after = (await response.json())["seconds"]
            latencies = sorted(value for result in results for value in result)
            pipe.send(
                {
                    "requests": len(latencies),
                    "errors": 0,
                    "elapsed_seconds": elapsed,
                    "completed_requests_per_second": len(latencies) / elapsed,
                    "offered_requests": count,
                    "load_model": "closed loop, 16 persistent connections",
                    "mean_seconds": statistics.mean(latencies),
                    "p95_seconds": latencies[(95 * len(latencies) + 99) // 100 - 1],
                    "latencies_seconds": latencies,
                    "client_cpu_fraction": cpu_elapsed / elapsed,
                    "server_cpu_fraction": (after - before) / elapsed,
                }
            )


def _client(pipe: Connection, port: int) -> None:
    _pin(1)
    asyncio.run(_client_loop(pipe, port))


class SocketWorkload:
    def __init__(self) -> None:
        # Spawn reads interpreter flags and environment, not the worker's mutable sys flag.
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        context = multiprocessing.get_context("spawn")
        self.server_pipe, server_child = context.Pipe()
        self.client_pipe, client_child = context.Pipe()
        self.server = context.Process(target=_server, args=(server_child,))
        self.client = context.Process(target=_client, args=(client_child, 0))
        self.server.start()
        try:
            self.metadata = self._receive(self.server_pipe)
            self.client = context.Process(
                target=_client, args=(client_child, self.metadata["port"])
            )
            self.client.start()
            self.metadata["client"] = self._receive(self.client_pipe)
            assert self.metadata["binding"] == self.metadata["client"]["binding"] == _binding()
            assert self.metadata["bytecode_writes_disabled"]
            assert self.metadata["client"]["bytecode_writes_disabled"]
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _receive(pipe: Connection) -> Any:
        if not pipe.poll(30):
            raise RuntimeError("HTTP child did not reply within thirty seconds")
        return pipe.recv()

    def prepare(self, route: str, count: int) -> None:
        assert count > 0
        assert count % 16 == 0
        self.client_pipe.send((route, count))
        assert self._receive(self.client_pipe) == {"prepared": True}

    def run(self) -> None:
        self.client_pipe.send("run")
        assert self._receive(self.client_pipe) == {"done": True}

    def collect(self) -> dict[str, Any]:
        self.client_pipe.send("collect")
        return self._receive(self.client_pipe)

    def batch(self, route: str, count: int) -> dict[str, Any]:
        self.prepare(route, count)
        self.run()
        result = self.collect()
        assert result["requests"] == count
        return result

    def close(self) -> None:
        for process in (self.client, self.server):
            if process.pid is not None:
                process.terminate()
                process.join(10)
                if process.is_alive():
                    process.kill()
                    process.join(5)
                assert not process.is_alive()
        self.client_pipe.close()
        self.server_pipe.close()


if __name__ == "__main__":
    workload = SocketWorkload()
    try:
        samples = [workload.batch(route, 32) for route in ("/small", "/large", "/plain")]
        Path(sys.argv[1]).write_text(
            json.dumps({"metadata": workload.metadata, "smoke": samples}, indent=2) + "\n"
        )
    finally:
        workload.close()
