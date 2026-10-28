"""Record mixed-graph, request and compile memory without timing claims."""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import tracemalloc
import weakref
from pathlib import Path

from diwire import Container, Lifetime, Scope
from tests.performance.measure_compile_memory import measure_compile_memory
from tests.performance.one_positional_socket import Consumer, Payload, make_container, payload
from tools.bb_perf_compare import fingerprint, runtime_metadata, verify_binding


async def graph_memory(*, request_scope: bool) -> dict[str, object]:
    """Measure 10,000 public resolutions and verify that values are released."""
    gc.collect()
    tracemalloc.start(1)
    try:
        initial, _ = tracemalloc.get_traced_memory()
        if request_scope:
            container = make_container()
        else:
            container = Container()
            container.add_factory(payload, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
            container.add(Consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
        resolver = container.compile()
        released = 0
        references: tuple[weakref.ReferenceType[object], ...] = ()
        for _ in range(10_000):
            if request_scope:
                async with resolver.enter_scope(Scope.REQUEST) as scope:
                    value = await scope.aresolve(Consumer)
                del scope
            else:
                value = await resolver.aresolve(Consumer)
            if not isinstance(value.payload, Payload):
                raise TypeError("Incorrect mixed graph")
            references = (weakref.ref(value), weakref.ref(value.payload))
            del value
            if any(reference() is not None for reference in references):
                raise RuntimeError("Transient results remain alive after resolution")
            released += len(references)
        _, peak = tracemalloc.get_traced_memory()
        gc.collect()
        retained, _ = tracemalloc.get_traced_memory()
        await container.aclose()
        del resolver, container
        gc.collect()
        if any(reference() is not None for reference in references):
            raise RuntimeError("Resolved values remain alive after close")
        return {
            "retained_bytes": retained - initial,
            "peak_bytes": peak - initial,
            "released_values": released,
        }
    finally:
        tracemalloc.stop()


def inputs(subject: Path) -> dict[str, object]:
    """Record every declared cell and its exact subject binding."""
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
    }


def main() -> None:
    """Write one fresh-process record without overwriting earlier evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--subject-root", type=Path, required=True)
    args = parser.parse_args()
    result = inputs(args.subject_root.resolve())
    result["mixed_graph"] = asyncio.run(graph_memory(request_scope=False))
    result["request_graph"] = asyncio.run(graph_memory(request_scope=True))
    result["compile"] = [measure_compile_memory(count) for count in (64, 256)]
    final = inputs(args.subject_root.resolve())
    result["final_inputs"] = final
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    if final != {key: result[key] for key in final}:
        raise RuntimeError("Memory inputs changed during measurement")


if __name__ == "__main__":
    main()
