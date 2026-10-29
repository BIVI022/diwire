"""Check required socket latency and memory evidence without sample selection."""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

PREFIX = (
    "tests/performance/test_collection_socket_workloads.py::test_benchmark_diwire_collection_socket"
)
CELLS = tuple(f"{PREFIX}[{mode}]" for mode in ("sync", "async", "mixed"))


def positive(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Missing numeric metric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Metrics must be positive and finite")
    return result


def validate_samples(
    samples: list[dict[str, Any]], raw: list[float], memory: list[dict[str, int]]
) -> tuple[list[float], list[dict[str, int]]]:
    for sample in samples:
        if len(sample["latencies"]) != 2048 or len(sample["client_latencies"]) != 2048:
            raise ValueError("Missing request durations")
        for value in [*sample["latencies"], *sample["client_latencies"]]:
            positive(value)
    for measured, sample in zip(raw, samples[2:], strict=True):
        if not math.isclose(
            positive(measured), positive(sample["server_seconds"]), rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError("Benchmark clock differs from complete server window")
    durations = sorted(value for sample in samples[2:] for value in sample["latencies"])
    if len(memory) != 5 or any(sample["scopes"] != 1000 for sample in memory):
        raise ValueError("Missing fixed memory blocks")
    return durations, memory


def metrics(path: Path) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text())
    result: dict[str, dict[str, float]] = {}
    for benchmark in payload["benchmarks"]:
        node = benchmark["fullname"]
        if node not in CELLS or node in result:
            raise ValueError("Unexpected or duplicate cell")
        info = benchmark["extra_info"]
        samples = info["server_samples"]
        raw = benchmark["stats"]["data"]
        if len(samples) != 9 or len(raw) != 7 or info["warmup_rounds"] != 2:
            raise ValueError("Expected all two warmups and seven measured server batches")
        binding = json.loads(path.with_suffix(".binding.json").read_text())
        if info["subject"] != binding["initial_binding"]["diwire"]:
            raise ValueError("Socket server subject mismatch")
        durations, memory = validate_samples(samples, raw, info["memory_samples"])
        client_durations = sorted(
            value for sample in samples[2:] for value in sample["client_latencies"]
        )
        result[node] = {
            "mean": statistics.mean(durations),
            "client_mean": statistics.mean(client_durations),
            "client_p95": client_durations[(95 * len(client_durations) + 99) // 100 - 1],
            "server_cpu_floor": min(
                positive(sample["server_cpu_seconds"]) / positive(sample["server_seconds"])
                for sample in samples[2:]
            ),
            "client_cpu_ceiling": max(
                positive(sample["client_cpu_seconds"]) / positive(sample["client_wall_seconds"])
                for sample in samples[2:]
            ),
            "p95": durations[(95 * len(durations) + 99) // 100 - 1],
            "peak": statistics.median(positive(sample["peak"]) for sample in memory),
            "retained": statistics.median(positive(sample["retained"]) for sample in memory),
        }
    if set(result) != set(CELLS):
        raise ValueError("Incomplete socket matrix")
    return result


def check(directory: Path) -> dict[str, object]:
    calibration = [metrics(directory / f"calibration-{index:02}-base.json") for index in range(3)]
    pairs = [
        (
            metrics(directory / f"pair-{index:02}-base.json"),
            metrics(directory / f"pair-{index:02}-next.json"),
        )
        for index in range(5)
    ]
    failures: list[str] = []
    ratios: dict[str, dict[str, list[float]]] = {}
    for node in CELLS:
        ratios[node] = {}
        failures.extend(
            f"{node}: fixed load does not prove server saturation"
            for sample in [
                *calibration,
                *(base for base, _ in pairs),
                *(candidate for _, candidate in pairs),
            ]
            if sample[node]["server_cpu_floor"] < 0.75 or sample[node]["client_cpu_ceiling"] > 0.85
        )
        for metric in ("mean", "p95", "client_mean", "client_p95", "peak", "retained"):
            values = [candidate[node][metric] / base[node][metric] for base, candidate in pairs]
            ratios[node][metric] = values
            if max(values) > 1.02:
                failures.append(f"{node}: {metric} exceeds 2% in at least one pair")
            # Retain and inspect the same spread ceiling as the throughput guard.
            for label, samples in (
                ("calibration", [sample[node][metric] for sample in calibration]),
                ("baseline", [base[node][metric] for base, _ in pairs]),
                ("candidate", [candidate[node][metric] for _, candidate in pairs]),
            ):
                if max(samples) - min(samples) > 0.03 * statistics.median(samples):
                    failures.append(f"{node}: {metric} {label} spread exceeds 3%")
    return {
        "outcome": "inconclusive" if failures else "accepted",
        "failures": failures,
        "pair_ratios": ratios,
        "scope": "socket latency and traced scope memory only",
    }


if __name__ == "__main__":
    try:
        receipt = check(Path(sys.argv[1]))
    except (KeyError, ValueError, TypeError, OSError, IndexError) as error:
        sys.stdout.write(json.dumps({"outcome": "error", "reason": str(error)}, indent=2) + "\n")
        sys.exit(3)
    sys.stdout.write(json.dumps(receipt, indent=2) + "\n")
    sys.exit(0 if receipt["outcome"] == "accepted" else 2)
