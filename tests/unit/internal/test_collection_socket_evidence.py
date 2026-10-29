"""Reject incomplete or regressed socket receipts before a speed claim."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.performance.socket_checks import CELLS, check, metrics


def payload() -> dict[str, Any]:
    sample = {
        "server_seconds": 1.0,
        "server_cpu_seconds": 0.8,
        "client_cpu_seconds": 0.5,
        "client_wall_seconds": 1.0,
        "latencies": [0.001] * 2048,
        "client_latencies": [0.002] * 2048,
    }
    return {
        "benchmarks": [
            {
                "fullname": cell,
                "stats": {"data": [1.0] * 7},
                "extra_info": {
                    "subject": "/subject/src/diwire/__init__.py",
                    "warmup_rounds": 2,
                    "server_samples": [deepcopy(sample) for _ in range(9)],
                    "memory_samples": [
                        {"retained": 1000, "peak": 2000, "scopes": 1000} for _ in range(5)
                    ],
                },
            }
            for cell in CELLS
        ]
    }


def write_sample(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data))
    path.with_suffix(".binding.json").write_text(
        json.dumps(
            {
                "initial_binding": {"diwire": "/subject/src/diwire/__init__.py"},
            }
        )
    )


@pytest.mark.parametrize("fault", ["subject", "rounds", "clock", "memory", "requests", "missing"])
def test_socket_receipt_rejects_incomplete_or_misbound_samples(tmp_path: Path, fault: str) -> None:
    data = payload()
    info = data["benchmarks"][0]["extra_info"]
    if fault == "subject":
        info["subject"] = "/controller/src/diwire/__init__.py"
    elif fault == "rounds":
        data["benchmarks"][0]["stats"]["data"].pop()
    elif fault == "clock":
        data["benchmarks"][0]["stats"]["data"][0] = 1.1
    elif fault == "memory":
        info["memory_samples"].pop()
    elif fault == "requests":
        info["server_samples"][0]["latencies"].pop()
    else:
        data["benchmarks"].pop()
    path = tmp_path / "sample-base.json"
    write_sample(path, data)
    with pytest.raises(ValueError, match=r"(mismatch|Expected|differs|Missing|Incomplete)"):
        metrics(path)


def apply_fault(info: dict[str, Any], fault: str) -> None:
    if fault == "memory":
        for block in info["memory_samples"]:
            block["peak"] = 2041
    elif fault == "latency":
        for batch in info["server_samples"]:
            batch["client_latencies"] = [0.002041] * 2048
    elif fault == "client":
        info["server_samples"][2]["client_cpu_seconds"] = 0.86
    elif fault == "server":
        info["server_samples"][2]["server_cpu_seconds"] = 0.74


@pytest.mark.parametrize("fault", ["none", "memory", "latency", "client", "server", "spread"])
def test_socket_gate_keeps_each_pair_and_enforces_auxiliary_limits(
    tmp_path: Path, fault: str
) -> None:
    data = payload()
    for label in [
        *(f"calibration-{i:02}-base" for i in range(3)),
        *(f"pair-{i:02}-{role}" for i in range(5) for role in ("base", "next")),
    ]:
        sample = deepcopy(data)
        info = sample["benchmarks"][0]["extra_info"]
        if label == "pair-04-next":
            apply_fault(info, fault)
        if label == "calibration-02-base" and fault == "spread":
            for block in info["memory_samples"]:
                block["retained"] = 1031
        write_sample(tmp_path / f"{label}.json", sample)
    result = check(tmp_path)
    assert result["outcome"] == ("accepted" if fault == "none" else "inconclusive")
