from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import time
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from tools import bb_perf_compare as compare

TARGET = "tests/benchmarks/test_cells.py::test_target"
PROTECTED = "tests/benchmarks/test_cells.py::test_protected"


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "targets": [TARGET],
        "protected": [PROTECTED],
        "practical_gain_floor": 0.03,
        "allowed_regression": 0.02,
        "baseline_spread_ceiling": 0.02,
        "pair_count": 5,
        "calibration_count": 3,
        "process_timeout_seconds": 120,
        "maximum_seconds": 4200,
        "plan_path": "plans/experiment.md",
        "gain_rationale": "The target workload needs at least three percent more throughput.",
    }


def _protocol(**changes: object) -> compare.Protocol:
    payload = _payload() | changes
    return compare.parse_protocol(json.dumps(payload).encode())


def _sample(target: float = 1, protected: float = 1) -> dict[str, float]:
    return {TARGET: target, PROTECTED: protected}


def _decision(
    candidate: float = 0.9,
    protected: float = 1,
    *,
    identical: bool = False,
) -> dict[str, object]:
    return compare.analyze(
        _protocol(),
        [_sample()] * 3,
        [(_sample(), _sample(candidate, protected))] * 5,
        identical_source=identical,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("extra", 1),
        ("pair_count", 4),
        ("pair_count", 21),
        ("pair_count", 5.0),
        ("calibration_count", 2),
        ("calibration_count", 11),
        ("process_timeout_seconds", 0),
        ("process_timeout_seconds", 601),
        ("maximum_seconds", 59),
        ("maximum_seconds", 4201),
        ("practical_gain_floor", 0),
        ("practical_gain_floor", -1),
        ("practical_gain_floor", float("nan")),
        ("practical_gain_floor", 10**400),
        ("practical_gain_floor", True),
        ("allowed_regression", 0.26),
        ("allowed_regression", float("inf")),
        ("baseline_spread_ceiling", 0),
        ("baseline_spread_ceiling", 0.26),
        ("plan_path", "../outside"),
        ("plan_path", "/absolute"),
        ("plan_path", "a/./b"),
        ("plan_path", "a\\b"),
        ("gain_rationale", " "),
        ("gain_rationale", None),
        ("targets", []),
        ("targets", ["-k"]),
        ("targets", ["tests/test.py"]),
        ("targets", ["../test.py::test_x"]),
        ("targets", ["tools/test.py::test_x"]),
        ("targets", ["tests/test.txt::test_x"]),
        ("targets", ["tests/test.py::test x"]),
        ("targets", ["tests/test.py::"]),
        ("protected", [TARGET]),
        ("targets", [TARGET, TARGET]),
        ("targets", [f"tests/test.py::test_{index}" for index in range(33)]),
    ],
)
def test_protocol_rejects_invalid_or_unbounded_rules(key: str, value: object) -> None:
    with pytest.raises(compare.ComparisonError):
        _protocol(**{key: value})


def test_protocol_requires_every_threshold_and_rejects_duplicate_keys() -> None:
    payload = _payload()
    del payload["practical_gain_floor"]
    with pytest.raises(compare.ComparisonError, match="fields"):
        compare.parse_protocol(json.dumps(payload).encode())
    with pytest.raises(compare.ComparisonError, match="Duplicate"):
        compare.parse_protocol(b'{"pair_count": 5, "pair_count": 20}')
    with pytest.raises(compare.ComparisonError, match="JSON object"):
        compare.parse_protocol(b"[]")


def test_protocol_keeps_preregistered_values() -> None:
    protocol = _protocol()
    assert protocol.cells == (TARGET, PROTECTED)
    assert protocol.practical_gain_floor == 0.03
    assert protocol.pair_count == 5


def test_all_targets_and_protected_cells_must_pass() -> None:
    result = _decision()
    assert result["status"] == "accepted"
    cells = compare.object_value(result["cells"])
    target = compare.object_value(cells[TARGET])
    assert target["pair_wins"] == 5
    assert target["median_throughput_effect"] == pytest.approx(1 / 0.9 - 1)
    assert target["median_time_effect"] == pytest.approx(-0.1)
    assert target["throughput_interval"] == pytest.approx([1 / 0.9 - 1] * 2)
    assert target["median_interval_coverage_under_independence"] == 0.9375


@pytest.mark.parametrize("candidate", [1, 1.01, 0.99])
def test_neutral_slower_or_subfloor_target_is_rejected(candidate: float) -> None:
    assert _decision(candidate)["status"] == "rejected"


def test_identical_source_cannot_be_accepted_even_with_favorable_timings() -> None:
    result = _decision(identical=True)
    assert result["status"] == "rejected"
    assert "identical source" in str(result["reason"])
    assert _decision(1, identical=True)["status"] == "rejected"


def test_protected_regression_rejects_an_apparent_target_win() -> None:
    assert _decision(protected=1.03)["status"] == "rejected"


def test_exact_regression_tolerance_is_inclusive_without_widening() -> None:
    assert _decision(protected=1.02)["status"] == "accepted"
    assert _decision(protected=1.020000001)["status"] == "rejected"


def test_exact_practical_floor_is_not_a_gain_beyond_the_floor() -> None:
    assert _decision(candidate=1 / 1.03)["status"] == "rejected"


def test_uncertain_regression_is_inconclusive() -> None:
    pairs = [(_sample(), _sample(0.9, value)) for value in (1.015, 1.015, 1.025, 1.025, 1.02)]
    assert compare.analyze(_protocol(), [_sample()] * 3, pairs)["status"] == "inconclusive"


def test_noisy_baseline_is_inconclusive_even_with_large_candidate_gain() -> None:
    calibration = [_sample(value) for value in (0.9, 1, 1.1)]
    result = compare.analyze(_protocol(), calibration, [(_sample(), _sample(0.5))] * 5)
    assert result["status"] == "inconclusive"


def test_candidate_process_instability_is_inconclusive() -> None:
    pairs = [(_sample(), _sample(value)) for value in (0.8, 0.9, 0.8, 0.9, 0.8)]
    assert compare.analyze(_protocol(), [_sample()] * 3, pairs)["status"] == "inconclusive"


def test_gain_must_clear_floor_and_noise_without_adding_them() -> None:
    calibration = [_sample(value) for value in (0.991, 1, 1.009)]
    result = compare.analyze(_protocol(), calibration, [(_sample(), _sample(1 / 1.04))] * 5)
    assert result["status"] == "accepted"


def test_each_target_pair_need_not_clear_the_practical_floor() -> None:
    pairs = [(_sample(), _sample(value)) for value in (0.99, 0.95, 0.95, 0.95, 0.95)]
    result = compare.analyze(_protocol(baseline_spread_ceiling=0.1), [_sample()] * 3, pairs)
    assert result["status"] == "accepted"


def test_every_target_must_pass_and_uncertainty_is_not_averaged_away() -> None:
    second = "tests/benchmarks/test_cells.py::test_other"
    protocol = _protocol(targets=[TARGET, second])
    baseline = _sample() | {second: 1}
    candidate = _sample(0.5) | {second: 1}
    assert (
        compare.analyze(protocol, [baseline] * 3, [(baseline, candidate)] * 5)["status"]
        == "rejected"
    )


@pytest.mark.parametrize("sample", [{TARGET: 1.0}, _sample(-1), _sample(float("nan"))])
def test_analysis_rejects_missing_or_invalid_cells(sample: dict[str, float]) -> None:
    with pytest.raises(compare.ComparisonError):
        compare.analyze(_protocol(), [sample] * 3, [(_sample(), _sample())] * 5)


def test_analysis_rejects_missing_processes() -> None:
    with pytest.raises(compare.ComparisonError, match="count"):
        compare.analyze(_protocol(), [_sample()] * 2, [(_sample(), _sample())] * 5)


def _raw(path: Path, *, data: object = None, rounds: int = 3) -> Path:
    payload = {
        "benchmarks": [
            {
                "fullname": node,
                "stats": {"data": data if data is not None else [1, 2, 3], "rounds": rounds},
            }
            for node in (TARGET, PROTECTED)
        ]
    }
    path.write_text(json.dumps(payload))
    return path


def test_raw_parser_uses_all_rounds_and_checks_complete_matrix(tmp_path: Path) -> None:
    raw = _raw(tmp_path / "raw.json", data=[1, 2, 100])
    assert compare.parse_benchmarks(raw, (TARGET, PROTECTED)) == _sample(2, 2)
    with pytest.raises(compare.ComparisonError, match="Unexpected"):
        compare.parse_benchmarks(raw, (TARGET,))
    with pytest.raises(compare.ComparisonError, match="Missing benchmark"):
        compare.parse_benchmarks(raw, (TARGET, PROTECTED, "missing"))


@pytest.mark.parametrize("data", [[1], [0, 1, 2], [float("nan"), 1, 2], "missing"])
def test_raw_parser_requires_positive_full_distributions(tmp_path: Path, data: object) -> None:
    with pytest.raises(compare.ComparisonError):
        compare.parse_benchmarks(_raw(tmp_path / "raw.json", data=data), (TARGET, PROTECTED))


def test_raw_parser_rejects_duplicate_cells(tmp_path: Path) -> None:
    raw = _raw(tmp_path / "raw.json")
    payload = json.loads(raw.read_text())
    payload["benchmarks"].append(payload["benchmarks"][0])
    raw.write_text(json.dumps(payload))
    with pytest.raises(compare.ComparisonError, match="duplicate"):
        compare.parse_benchmarks(raw, (TARGET, PROTECTED))


def test_binding_rejects_controller_install_and_mixed_submodules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = tmp_path / "subject"
    package = subject / "src/diwire"
    package.mkdir(parents=True)
    for name in tuple(sys.modules):
        if name == "diwire" or name.startswith("diwire."):
            monkeypatch.delitem(sys.modules, name)
    module = ModuleType("diwire")
    module.__file__ = str(tmp_path / "controller/src/diwire/__init__.py")
    monkeypatch.setitem(sys.modules, "diwire", module)
    with pytest.raises(compare.ComparisonError, match="Import misbinding"):
        compare.verify_binding(subject)
    module.__file__ = str(package / "__init__.py")
    assert compare.verify_binding(subject) == {"diwire": module.__file__}
    stray = ModuleType("diwire.internal")
    stray.__file__ = str(tmp_path / "controller/src/diwire/internal.py")
    monkeypatch.setitem(sys.modules, "diwire.internal", stray)
    with pytest.raises(compare.ComparisonError, match=r"diwire\.internal"):
        compare.verify_binding(subject)


def _runner(tmp_path: Path, *, distinct: bool = False) -> compare.Runner:
    subjects = {role: tmp_path / role for role in ("base", "next")}
    for role, root in subjects.items():
        source = root / "src/diwire"
        source.mkdir(parents=True)
        (source / "__init__.py").write_text(f'MARKER = "{role if distinct else "same"}"\n')
    return compare.Runner(
        _protocol(),
        tmp_path,
        subjects,
        {role: compare.fingerprint(root) for role, root in subjects.items()},
        time.monotonic() + 120,
    )


def test_runner_uses_fixed_alternating_sequence_and_does_not_stop_after_noise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(tmp_path)
    calls: list[tuple[str, str]] = []

    def measure(self: compare.Runner, label: str, role: str) -> dict[str, float]:
        calls.append((label, role))
        return _sample(2 if label == "calibration-01" else 1)

    monkeypatch.setattr(compare.Runner, "measure", measure)
    assert runner.run()["status"] == "inconclusive"
    assert calls[:3] == [(f"calibration-{index:02}", "base") for index in range(3)]
    assert [role for _, role in calls[3:]] == [
        "base",
        "next",
        "next",
        "base",
        "base",
        "next",
        "next",
        "base",
        "base",
        "next",
    ]


def test_runner_checks_inactive_subject_before_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(tmp_path)

    def measure(self: compare.Runner, label: str, role: str) -> dict[str, float]:
        if label == "pair-04" and role == "next":
            (self.subjects["base"] / "src/diwire/__init__.py").write_text("late write\n")
        return _sample()

    monkeypatch.setattr(compare.Runner, "measure", measure)
    with pytest.raises(compare.ComparisonError, match="changed before analysis"):
        runner.run()


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Worker isolation needs Python -P (3.11+); official measurements use pinned 3.14.7",
)
def test_real_worker_imports_each_archived_subject_and_keeps_raw_data(tmp_path: Path) -> None:
    runner = _runner(tmp_path, distinct=True)
    test_source = """import diwire

def test_target(benchmark):
    benchmark.extra_info["subject_marker"] = diwire.MARKER
    benchmark.pedantic(lambda: diwire.MARKER, rounds=3, iterations=1)

def test_protected(benchmark):
    benchmark.pedantic(lambda: None, rounds=3, iterations=1)
"""
    for role, root in runner.subjects.items():
        tests = root / "tests/benchmarks"
        tests.mkdir(parents=True)
        (tests / "test_cells.py").write_text(test_source)
        runner.manifests[role] = compare.fingerprint(root)
        assert set(runner.measure("smoke", role)) == {TARGET, PROTECTED}
        raw = compare.read_json((tmp_path / f"smoke-{role}.json").read_bytes())
        entries = raw["benchmarks"]
        assert isinstance(entries, list)
        entry = compare.object_value(entries[0])
        assert compare.object_value(entry["extra_info"])["subject_marker"] == role
        binding = compare.read_json((tmp_path / f"smoke-{role}.binding.json").read_bytes())
        paths = compare.object_value(binding["final_binding"])
        assert paths["diwire"] == str(root / "src/diwire/__init__.py")
        assert binding["initial_runtime"] == binding["runtime"]


def test_runner_timeout_does_not_retry_and_keeps_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compare, "snapshot", dict)
    runner = _runner(tmp_path)
    calls = 0

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired("pytest", 1)

    monkeypatch.setattr("tools.bb_perf_compare.subprocess.run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        runner.measure("timeout", "base")
    assert calls == 1
    assert (tmp_path / "timeout-base.command.json").is_file()


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Worker isolation needs Python -P (3.11+); official measurements use pinned 3.14.7",
)
def test_real_worker_rejects_import_rebinding_during_collection(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    root = runner.subjects["base"]
    tests = root / "tests/benchmarks"
    tests.mkdir(parents=True)
    (tests / "test_cells.py").write_text(
        'import diwire\ndiwire.__file__ = "/controller/src/diwire/__init__.py"\n'
        "def test_target(benchmark):\n    benchmark(lambda: None)\n"
        "def test_protected(benchmark):\n    benchmark(lambda: None)\n",
    )
    runner.manifests["base"] = compare.fingerprint(root)
    with pytest.raises(compare.ComparisonError, match="Measurement failed"):
        runner.measure("misbinding", "base")
    assert "Import misbinding" in (tmp_path / "misbinding-base.log").read_text()


def test_runner_rejects_changed_runtime_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compare, "snapshot", dict)
    runner = _runner(tmp_path)
    runner.runtime = {"dependencies": "original"}

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        compare.save(
            tmp_path / "changed-base.binding.json",
            {
                "initial_runtime": {"dependencies": "changed"},
                "runtime": {"dependencies": "changed"},
            },
        )
        return subprocess.CompletedProcess("pytest", 0)

    monkeypatch.setattr("tools.bb_perf_compare.subprocess.run", run)
    with pytest.raises(compare.ComparisonError, match="Runtime or dependency metadata changed"):
        runner.measure("changed", "base")


def test_unpack_rejects_links_without_touching_external_files(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        entry = tarfile.TarInfo("src/diwire")
        entry.type = tarfile.SYMTYPE
        entry.linkname = str(tmp_path / "external")
        archive.addfile(entry)
    with pytest.raises(compare.ComparisonError, match="non-regular"):
        compare.unpack(stream.getvalue(), tmp_path / "subject")
    assert not (tmp_path / "external").exists()


def test_snapshot_tolerates_disappearing_process_files(tmp_path: Path) -> None:
    assert "unavailable" in compare.optional_read(tmp_path / "gone")


def _arguments(output: Path) -> list[str]:
    return [
        "--base-sha",
        "a" * 40,
        "--candidate-sha",
        "b" * 40,
        "--protocol",
        "plans/protocol.json",
        "--output",
        str(output),
    ]


@pytest.mark.parametrize("status", ["accepted", "rejected", "inconclusive", "error"])
def test_cli_exit_codes_and_partial_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    runner = _runner(tmp_path)

    def prepare(repo: Path, output: Path, args: argparse.Namespace) -> compare.Runner:
        if status == "error":
            raise compare.ComparisonError("invalid protocol")
        return runner

    monkeypatch.setattr(compare, "prepare", prepare)
    monkeypatch.setattr(compare.Runner, "run", lambda _self: {"status": status})
    output = tmp_path / "evidence"
    assert compare.main(_arguments(output)) == compare.EXIT_CODES[status]
    result = compare.read_json((output / "decision.json").read_bytes())
    assert result["status"] == status
    assert result["base_sha"] == "a" * 40
    assert result["candidate_sha"] == "b" * 40
    assert "tools.bb_perf_compare" in str(result["command"])


def test_cli_refuses_existing_output_and_preserves_user_files(tmp_path: Path) -> None:
    sentinel = tmp_path / "decision.json"
    sentinel.write_text("user data")
    assert compare.main(_arguments(tmp_path)) == 3
    assert sentinel.read_text() == "user data"


def test_usage_errors_have_error_exit_code() -> None:
    with pytest.raises(SystemExit) as error:
        compare.main([])
    assert error.value.code == 3


def test_declared_boundaries_do_not_move_with_results() -> None:
    protocol = _protocol()
    original = replace(protocol)
    compare.analyze(protocol, [_sample()] * 3, [(_sample(), _sample(0.9))] * 5)
    assert protocol == original


def _commit(repo: Path) -> str:
    compare.git(repo, "add", ".")
    compare.git(
        repo,
        "-c",
        "user.name=Maksim Zayats",
        "-c",
        "user.email=49313691+maksimzayats@users.noreply.github.com",
        "commit",
        "-qm",
        "test fixture",
    )
    return compare.git(repo, "rev-parse", "HEAD").decode().strip()


@pytest.fixture()
def frozen_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    compare.git(repo, "init", "-q")
    source = repo / "src/diwire"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('MARKER = "base"\n')
    (repo / "uv.lock").write_text("frozen lock\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "diwire"\n')
    base = _commit(repo)
    (source / "__init__.py").write_text('MARKER = "candidate"\n')
    plans = repo / "plans"
    plans.mkdir()
    (plans / "protocol.json").write_text(json.dumps(_payload()))
    (plans / "experiment.md").write_text(str(_payload()["gain_rationale"]))
    tests = repo / "tests/benchmarks"
    tests.mkdir(parents=True)
    (tests / "test_cells.py").write_text("# new candidate harness\n")
    return repo, base, _commit(repo)


def _repo_arguments(repo: Path, base: str, candidate: str) -> argparse.Namespace:
    return argparse.Namespace(
        repo=repo, base_sha=base, candidate_sha=candidate, protocol="plans/protocol.json"
    )


def test_prepare_freezes_new_candidate_harness_and_changes_only_library_source(
    tmp_path: Path,
    frozen_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, candidate = frozen_repo
    monkeypatch.setattr("tools.bb_perf_compare.platform.system", lambda: "Linux")
    monkeypatch.setattr("tools.bb_perf_compare.platform.python_version", lambda: "3.14.7")
    output = tmp_path / "evidence"
    output.mkdir()
    runner = compare.prepare(repo, output, _repo_arguments(repo, base, candidate))
    before, after = runner.subjects["base"], runner.subjects["next"]
    assert len(str(before)) == len(str(after))
    assert (before / "tests/benchmarks/test_cells.py").read_bytes() == (
        after / "tests/benchmarks/test_cells.py"
    ).read_bytes()
    assert (before / "src/diwire/__init__.py").read_text() == 'MARKER = "base"\n'
    assert (after / "src/diwire/__init__.py").read_text() == 'MARKER = "candidate"\n'
    inputs = compare.read_json((output / "inputs.json").read_bytes())
    assert inputs["base_sha"] == base
    assert inputs["candidate_sha"] == candidate
    assert inputs["protocol_sha256"] == compare.sha256((repo / "plans/protocol.json").read_bytes())
    assert inputs["plan_sha256"] == compare.sha256((repo / "plans/experiment.md").read_bytes())
    assert compare.git(repo, "status", "--porcelain") == b""


@pytest.mark.parametrize("filename", ["uv.lock", "pyproject.toml"])
def test_changed_dependency_inputs_are_rejected_before_measurement(
    frozen_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    repo, base, candidate = frozen_repo
    monkeypatch.setattr("tools.bb_perf_compare.platform.system", lambda: "Linux")
    monkeypatch.setattr("tools.bb_perf_compare.platform.python_version", lambda: "3.14.7")
    with (repo / filename).open("a") as stream:
        stream.write("changed\n")
    candidate = _commit(repo)
    with pytest.raises(compare.ComparisonError, match="dependencies/configuration differ"):
        compare.check_inputs(repo, _repo_arguments(repo, base, candidate))


def test_symbolic_revision_and_wrong_controller_are_rejected(
    frozen_repo: tuple[Path, str, str],
) -> None:
    repo, base, candidate = frozen_repo
    with pytest.raises(compare.ComparisonError, match="full lowercase"):
        compare.check_inputs(repo, _repo_arguments(repo, "HEAD~1", candidate))
    with pytest.raises(compare.ComparisonError, match="Controller HEAD"):
        compare.check_inputs(repo, _repo_arguments(repo, base, base))


def test_dirty_controller_is_rejected_without_restoring_user_work(
    frozen_repo: tuple[Path, str, str],
) -> None:
    repo, base, candidate = frozen_repo
    source = repo / "src/diwire/__init__.py"
    source.write_text("user changes\n")
    with pytest.raises(compare.ComparisonError, match="tracked files must be clean"):
        compare.check_inputs(repo, _repo_arguments(repo, base, candidate))
    assert source.read_text() == "user changes\n"
