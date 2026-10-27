"""Run the fixed Linux campaign, including mandatory latency and allocation gates."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tools import bb_perf_compare as compare

PLAN = "plans/2026-10-27-async-dependency-plan"
BASE = "2dc938211a2cfb82b89323d025ac434c6dd246d1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _status(cells: dict[str, dict[str, Any]]) -> str:
    statuses = {cell["status"] for cell in cells.values()}
    return next(
        (status for status in ("error", "inconclusive", "rejected") if status in statuses),
        "accepted",
    )


def _analyze(protocol: compare.Protocol, series: list[dict[str, float]]) -> dict[str, Any]:
    if len(series) != 21 or not series or any(set(row) != set(series[0]) for row in series):
        raise ValueError("Incomplete fixed sample series")
    cells = {}
    for node in series[0]:
        samples = [row[node] for row in series]
        if any(compare.number(value) <= 0 for value in samples):
            return {
                "status": "inconclusive",
                "reason": "Nonpositive protected metric denominator",
                "samples": series,
            }
        cells[node] = compare.analyze_cell(
            protocol, node, samples[:3], samples[3::2], samples[4::2]
        )
    return {"status": _status(cells), "cells": cells}


def _sequence() -> list[tuple[str, str]]:
    result = [(f"calibration-{index:02}", "base") for index in range(3)]
    for index in range(9):
        result.extend(
            (f"pair-{index:02}", role)
            for role in (("base", "next") if index % 2 == 0 else ("next", "base"))
        )
    return result


def analyze_http(directory: Path) -> dict[str, Any]:
    protocol = compare.parse_protocol((directory / "protocol.json").read_bytes())
    series = {}
    capacity = []
    # Normalize alternating execution order to base/candidate order for paired analysis.
    labels = [(f"calibration-{i:02}", "base") for i in range(3)]
    labels += [(f"pair-{i:02}", role) for i in range(9) for role in ("base", "next")]
    for label, role in labels:
        row = {}
        raw = _read(directory / f"{label}-{role}.json")
        entries = {entry["fullname"]: entry for entry in raw["benchmarks"]}
        if set(entries) != set(protocol.cells):
            raise ValueError("HTTP cells differ from protocol")
        for node, entry in entries.items():
            samples = entry["extra_info"]["http_samples"]
            if len(samples) != 10 or any(
                sample["errors"] != 0 or sample["requests"] != 8192 for sample in samples
            ):
                raise ValueError("Incomplete HTTP samples or HTTP errors")
            capacity.append(
                {
                    "label": label,
                    "role": role,
                    "node": node,
                    "pass": all(
                        sample["client_cpu_fraction"] < 0.70
                        and sample["server_cpu_fraction"] > 0.80
                        for sample in samples
                    ),
                }
            )
            for field in ("elapsed_seconds", "mean_seconds", "p95_seconds"):
                # The elapsed field uses the throughput target's node ID and gain floor.
                key = node if field == "elapsed_seconds" else node + ":" + field
                row[key] = statistics.median(sample[field] for sample in samples[3:])
        series[label, role] = row
    ordered = [series[label, role] for label, role in labels]
    result = _analyze(protocol, ordered)
    result["capacity"] = capacity
    if not all(row["pass"] for row in capacity):
        result.update(
            status="inconclusive", reason="Client capacity or server utilization gate failed"
        )
    return result


def _probe(subject: Path, output: Path, command: list[str], deadline: float) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Auxiliary campaign budget exhausted")
    environment = dict(os.environ)
    for name in (
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONTRACEMALLOC",
        "PYTHONPROFILEIMPORTTIME",
    ):
        environment.pop(name, None)
    environment.update(
        PYTHONPATH=os.pathsep.join((str(subject / "src"), str(subject))),
        PYTHONHASHSEED="0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    argv = [sys.executable, "-B", "-s", *command, str(output)]
    compare.save(
        output.with_suffix(".command.json"),
        {"argv": argv, "subject": str(subject), "machine": compare.snapshot()},
    )
    with output.with_suffix(".log").open("x") as log:
        subprocess.run(  # noqa: S603 - fixed interpreter and argument list, no shell
            argv,
            cwd=subject,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=min(180, remaining),
            check=True,
        )
    return _read(output)


def run_auxiliary(comparison: Path, output: Path) -> dict[str, Any]:
    output.mkdir()
    inputs = _read(comparison / "inputs.json")
    subjects = {role: comparison / "subjects" / role for role in ("base", "next")}
    for role, subject in subjects.items():
        if compare.fingerprint(subject) != inputs["manifests"][role]:
            raise ValueError("Frozen auxiliary subject differs from comparison")
    protocol = compare.parse_protocol((comparison / "protocol.json").read_bytes())
    deadline = time.monotonic() + 4200
    groups = {}
    specs = [
        ("startup-" + scenario, ["tests/performance/startup_probe.py", scenario])
        for scenario in ("import", "explicit", "autoregister", "settings_first", "diwire_first")
    ]
    specs += [("compile-memory", ["-m", "tests.performance.measure_compile_memory", "--output"])]
    specs += [
        (
            f"graph-memory-{edges}",
            ["-m", "tests.performance.dependency_plan_memory", "--edges", str(edges), "--output"],
        )
        for edges in (5, 17)
    ]
    for name, command in specs:
        values = {}
        for label, role in _sequence():
            raw = _probe(subjects[role], output / f"{name}-{label}-{role}.json", command, deadline)
            manifest = inputs["manifests"][role]
            hashes = raw.get(
                "source_sha256", raw.get("hashes", raw.get("context", {}).get("source_sha256"))
            )
            expected = {
                path: digest
                for path, digest in manifest.items()
                if path.startswith("src/diwire/") and path.endswith(".py")
            }
            if hashes is None or {path: hashes[path] for path in expected} != expected:
                raise ValueError("Auxiliary probe source binding differs")
            if name.startswith("startup-"):
                metrics = {name + ":total_ns": raw["timings_ns"]["total_ns"]}
            elif name == "compile-memory":
                metrics = {
                    f"{name}:{row['provider_count']}:{metric}": row[metric]
                    for row in raw["measurements"]
                    for metric in ("retained_bytes", "peak_bytes")
                }
            else:
                metrics = {
                    name + ":" + metric: raw["measurements"][metric]
                    for metric in ("retained_bytes", "peak_bytes")
                }
            values[label, role] = metrics
            if compare.fingerprint(subjects[role]) != manifest:
                raise ValueError("Auxiliary probe changed frozen files")
        labels = [(f"calibration-{i:02}", "base") for i in range(3)]
        labels += [(f"pair-{i:02}", role) for i in range(9) for role in ("base", "next")]
        groups[name] = _analyze(protocol, [values[key] for key in labels])
        compare.save(output / f"{name}-analysis.json", groups[name])
        if groups[name]["status"] != "accepted":
            break
    return {"status": _status(groups), "groups": groups}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "status": "error",
        "base_sha": BASE,
        "candidate_sha": args.candidate_sha,
        "cohorts": {},
    }
    try:
        for name in ("public", "extended-a", "extended-b", "http"):
            directory = output / name
            code = compare.main(
                [
                    "--base-sha",
                    BASE,
                    "--candidate-sha",
                    args.candidate_sha,
                    "--protocol",
                    f"{PLAN}/{name}.json",
                    "--output",
                    str(directory),
                ]
            )
            decision = _read(directory / "decision.json")
            result["cohorts"][name] = decision
            if code:
                result["status"] = decision["status"]
                break
        else:
            result["http_gates"] = analyze_http(output / "http")
            result["status"] = result["http_gates"]["status"]
            if result["status"] == "accepted":
                result["auxiliary"] = run_auxiliary(output / "http", output / "auxiliary")
                result["status"] = result["auxiliary"]["status"]
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        compare.ComparisonError,
    ) as error:
        result.update(status="error", reason=f"{type(error).__name__}: {error}")
    finally:
        compare.save(output / "campaign-decision.json", result)
    return compare.EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
