"""Real loopback HTTP with a clock derived only from server request windows."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO, cast

import pytest

from tests.performance.collection_socket_app import AMOUNT, BATCH_SIZE, COMPONENTS, Mode

CONCURRENCY = 8
ROUNDS = 7
WARMUPS = 2


class ServerClock:
    """Use the sum of complete server windows as the pytest-benchmark timer."""

    port = 0

    def __call__(self) -> float:
        return float(read_json(self.port, "/stats")["clock"])


def read_json(port: int, path: str) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        assert response.status == 200
        return cast("dict[str, Any]", json.loads(response.read()))
    finally:
        connection.close()


_CLOCK = ServerClock()


def request_stream(port: int) -> tuple[list[int], list[float]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    sequences = []
    durations = []
    expected = sum(AMOUNT * (100 + index) // 100 for index in range(COMPONENTS))
    try:
        for _ in range(BATCH_SIZE // CONCURRENCY):
            started = time.perf_counter()
            connection.request("GET", "/work")
            response = connection.getresponse()
            assert response.status == 200
            body = response.read()
            durations.append(time.perf_counter() - started)
            result = json.loads(body)
            assert result["components"] == COMPONENTS
            assert result["total"] == expected
            sequences.append(result["request"])
    finally:
        connection.close()
    return sequences, durations


def wait_for_server(port: int, process: subprocess.Popen[str], log: TextIO) -> dict[str, Any]:
    def try_read() -> dict[str, Any] | None:
        try:
            initial = read_json(port, "/stats")
        except (OSError, http.client.HTTPException):
            return None
        else:
            return initial

    deadline = time.monotonic() + 20
    while True:
        initial = try_read()
        if initial is not None:
            return initial
        if process.poll() is not None or time.monotonic() >= deadline:
            log.seek(0)
            pytest.fail(f"Socket subject failed to start: {log.read()}")
        time.sleep(0.05)


@pytest.mark.parametrize("mode", ["sync", "async", "mixed"])
@pytest.mark.benchmark(timer=_CLOCK)
def test_benchmark_diwire_collection_socket(benchmark: Any, mode: Mode) -> None:
    """Keep one fresh server for each cell and process, with no measured startup."""
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    samples: list[dict[str, object]] = []
    with socket.socket() as listener, tempfile.TemporaryFile(mode="w+") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        _CLOCK.port = port
        process = subprocess.Popen(  # noqa: S603 - fixed module, no shell
            [
                sys.executable,
                "-m",
                "tests.performance.collection_socket_app",
                mode,
                str(listener.fileno()),
            ],
            cwd=root,
            env=environment,
            pass_fds=(listener.fileno(),),
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            initial = wait_for_server(port, process, log)
            assert initial["subject"] == str(root / "src/diwire/__init__.py")
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:

                def batch() -> None:
                    wall_started = time.perf_counter()
                    cpu_started = time.process_time()
                    results = list(executor.map(request_stream, [port] * CONCURRENCY))
                    cpu_seconds = time.process_time() - cpu_started
                    wall_seconds = time.perf_counter() - wall_started
                    sequences = [sequence for stream, _ in results for sequence in stream]
                    assert len(set(sequences)) == BATCH_SIZE
                    state = read_json(port, "/stats")
                    assert state["opened"] == state["closed"]
                    assert state["opened"] == state["batch"]["completed"]
                    sample = state["batch"]
                    sample.update(
                        client_cpu_seconds=cpu_seconds,
                        client_wall_seconds=wall_seconds,
                        client_latencies=[value for _, durations in results for value in durations],
                    )
                    samples.append(sample)

                benchmark.pedantic(batch, rounds=ROUNDS, warmup_rounds=WARMUPS, iterations=1)
            memory = [read_json(port, "/memory") for _ in range(5)]
            benchmark.extra_info.update(
                server_samples=samples,
                memory_samples=memory,
                subject=initial["subject"],
                concurrency=CONCURRENCY,
                operations_per_batch=BATCH_SIZE,
                warmup_rounds=WARMUPS,
                measured_rounds=ROUNDS,
                clock="sum of server windows: first ASGI arrival to final response body send",
                operation="socket GET; 16 pricing rules; fresh scoped resource; cleanup; 8 clients",
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            log.seek(0)
            benchmark.extra_info["server_log"] = log.read()
