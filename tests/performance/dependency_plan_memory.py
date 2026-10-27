"""Measure mixed graph allocations in one fresh process, separate from timing."""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import platform
import sys
import tracemalloc
from pathlib import Path

from diwire import Scope
from tests.performance.dependency_plan_workload import Result, build_graph, check_graph


async def measure(edges: int) -> dict[str, int]:
    gc.collect()
    tracemalloc.start(1)
    try:
        initial, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        resolver, _context, layers = build_graph(edges)
        for _ in range(100 + 10_000):
            async with resolver.enter_scope(Scope.REQUEST) as request:
                await request.aresolve(Result)
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    try:
        await check_graph(resolver, layers)
    finally:
        await resolver.aclose()
    return {"edges": edges, "retained_bytes": retained - initial, "peak_bytes": peak - initial}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edges", type=int, choices=(5, 17), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(measure(args.edges))
    root = Path(__file__).resolve().parents[2]
    paths = [
        *root.joinpath("src").rglob("*.py"),
        *root.joinpath("tests/performance").glob("*.py"),
        root / "uv.lock",
    ]
    payload = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "measurements": result,
        "hashes": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
    }
    with args.output.open("x") as output:
        json.dump(payload, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
