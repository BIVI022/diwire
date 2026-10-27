from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.performance import dependency_plan_campaign as campaign
from tools import bb_perf_compare as compare


def test_auxiliary_analysis_enforces_pairs_noise_and_regression() -> None:
    protocol = compare.parse_protocol(Path(campaign.PLAN, "public.json").read_bytes())
    assert campaign._analyze(protocol, [{"memory": 100.0}] * 21)["status"] == "accepted"
    regression = [{"memory": 100.0}] * 3 + [
        {"memory": value} for _ in range(9) for value in (100.0, 103.0)
    ]
    assert campaign._analyze(protocol, regression)["status"] == "rejected"
    noisy = [{"memory": value} for value in (100.0, 110.0, 100.0)] + [{"memory": 100.0}] * 18
    assert campaign._analyze(protocol, noisy)["status"] == "inconclusive"
    with pytest.raises(ValueError, match="Incomplete"):
        campaign._analyze(protocol, regression[:-1])
    assert campaign._analyze(protocol, [{"memory": 0.0}] * 21)["status"] == "inconclusive"


@pytest.mark.parametrize(
    ("latency", "capacity", "expected"),
    [(0.99, True, "accepted"), (1.03, True, "rejected"), (0.99, False, "inconclusive")],
)
def test_http_analysis_checks_extra_gates(
    tmp_path: Path, *, latency: float, capacity: bool, expected: str
) -> None:
    data = Path(campaign.PLAN, "http.json").read_bytes()
    (tmp_path / "protocol.json").write_bytes(data)
    protocol = compare.parse_protocol(data)
    for label, role in campaign._sequence():
        entries = []
        for node in protocol.cells:
            sample = {
                "requests": 8192,
                "errors": 0,
                "client_cpu_fraction": 0.50 if capacity else 0.90,
                "server_cpu_fraction": 0.90,
                "elapsed_seconds": 0.95 if role == "next" else 1.0,
                "mean_seconds": latency if role == "next" else 1.0,
                "p95_seconds": latency if role == "next" else 1.0,
            }
            entries.append({"fullname": node, "extra_info": {"http_samples": [sample] * 10}})
        (tmp_path / f"{label}-{role}.json").write_text(json.dumps({"benchmarks": entries}))
    assert campaign.analyze_http(tmp_path)["status"] == expected


def test_fixed_sequence_alternates_and_keeps_all_pairs() -> None:
    sequence = campaign._sequence()
    assert len(sequence) == 21
    assert sequence[3:7] == [
        ("pair-00", "base"),
        ("pair-00", "next"),
        ("pair-01", "next"),
        ("pair-01", "base"),
    ]
