"""Compare frozen Linux subjects without changing the caller's source tree.

Run with the candidate's locked dev/docs environment::

    uv run --locked python -m tools.bb_perf_compare --base-sha <40 hex> \
        --candidate-sha <40 hex> --protocol plans/experiment.json --output /tmp/new-evidence

Protocol schema 1 (all fractions, not percentages)::

    {"schema_version": 1,
     "targets": ["tests/benchmarks/test_x.py::test_target"],
     "protected": ["tests/benchmarks/test_y.py::test_protected"],
     "practical_gain_floor": 0.03, "allowed_regression": 0.02,
     "baseline_spread_ceiling": 0.02, "pair_count": 5, "calibration_count": 3,
     "process_timeout_seconds": 180, "maximum_seconds": 4200,
     "plan_path": "plans/experiment.md",
     "gain_rationale": "Explain why this workload needs the declared throughput gain."}

The plan must support the workload-specific floor and contain gain_rationale verbatim.
These example values are not defaults.
Unknown fields, duplicate keys and non-finite numbers are errors. Counts are bounded to
5..20 pairs, 3..10 calibration runs and 32 exact, distinct benchmark node IDs in total.
The gain floor is in (0, 1], regression in [0, .25], spread ceiling in (0, .25].
Process timeouts are 1..600 seconds; the complete measurement budget is 60..4200 seconds.

Each calibration is a fresh baseline process. Comparison pairs alternate AB/BA. A cell's
time is the median of ALL retained benchmark rounds. No rounds or processes are removed.
Uncertainty is the full range of paired effects, a conservative distribution-free median
interval with coverage 1 - 2**(1-n), assuming independent pairs. At five pairs this is 93.75%,
not a claimed 95% interval. Serial drift can violate that assumption. The separate spread
checks therefore cover calibration, baseline and candidate process medians. Target acceptance
requires median throughput gain above BOTH the practical floor and observed baseline spread,
plus an uncertainty lower bound above zero. The full-range interval deliberately requires
all pairs to show some gain, but each pair need not clear the practical floor. This avoids
bootstrap assumptions for small samples. Protected cells require EVERY paired time regression
to stay within the fixed tolerance. A protected interval that crosses that boundary is
inconclusive. This driver does not retry uncertain cells or widen tolerance. Any focused
confirmation needs a separate committed protocol with a fixed sample count. Missing cells
are errors.

Exit codes: 0 accepted, 1 rejected (includes identical source or insufficient benefit),
2 inconclusive (unstable or uncertain), 3 error (invalid inputs, binding, timeout or execution).
Argparse usage errors also use 3. decision.json links the exact commits, protocol, plan,
archives, per-file hashes, commands, raw data and environment. Partial evidence is retained.
The driver measures only. Quality gates belong to the workflow's optional quality mode.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, NoReturn, cast

EXIT_CODES: Final = {"accepted": 0, "rejected": 1, "inconclusive": 2, "error": 3}
MAX_CELLS: Final = 32
MIN_ROUNDS: Final = 2
SHA_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
SUBJECT: Final = "src/diwire"
PYTHON_VERSION: Final = "3.14.7"


class ComparisonError(ValueError):
    """The comparison cannot produce trustworthy evidence."""


@dataclass(frozen=True)
class Protocol:
    """Fixed, committed measurement and decision rules."""

    targets: tuple[str, ...]
    protected: tuple[str, ...]
    practical_gain_floor: float
    allowed_regression: float
    baseline_spread_ceiling: float
    pair_count: int
    calibration_count: int
    process_timeout_seconds: int
    maximum_seconds: int
    plan_path: str
    gain_rationale: str

    @property
    def cells(self) -> tuple[str, ...]:
        """Return the complete fixed matrix in execution order."""
        return self.targets + self.protected


def fail(message: str) -> NoReturn:
    """Raise a descriptive tool error without changing library exceptions."""
    raise ComparisonError(message)


def object_value(value: object) -> dict[str, object]:
    """Validate a JSON object at the untyped parser boundary."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        fail("Expected a JSON object with string keys")
    return cast("dict[str, object]", value)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys rather than silently changing declared thresholds."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(data: bytes) -> dict[str, object]:
    """Read strict JSON without accepting duplicate keys."""
    return object_value(json.loads(data, object_pairs_hook=unique_object))


def number(value: object) -> float:
    """Read a finite JSON number, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Expected a finite number")
    try:
        result = float(value)
    except OverflowError:
        fail("Number exceeds the supported finite range")
    if not math.isfinite(result):
        fail("Expected a finite number")
    return result


def bounded_number(payload: Mapping[str, object], key: str, upper: float) -> float:
    """Read a nonnegative, bounded decision threshold."""
    result = number(payload[key])
    if not 0 <= result <= upper:
        fail(f"{key} must be between zero and {upper}")
    return result


def count(payload: Mapping[str, object], key: str, low: int, high: int) -> int:
    """Read a bounded integer without numeric coercion."""
    value = payload[key]
    if type(value) is not int or not low <= value <= high:
        fail(f"{key} must be an integer in {low}..{high}")
    return value


def relative_path(value: object) -> str:
    """Require a plain repository-relative path with no traversal."""
    if not isinstance(value, str) or not value or "\\" in value:
        fail("Expected a repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        fail(f"Unsafe repository path: {value}")
    return value


def node_ids(value: object) -> tuple[str, ...]:
    """Require exact benchmark function IDs, including parameter suffixes."""
    if not isinstance(value, list) or not value:
        fail("Both targets and protected must be nonempty lists")
    nodes: list[str] = []
    for node in value:
        if not isinstance(node, str) or "::" not in node or any(c.isspace() for c in node):
            fail("Expected an exact benchmark node ID")
        filename, _, function = node.partition("::")
        relative_path(filename)
        if not filename.startswith("tests/") or not filename.endswith(".py") or not function:
            fail(f"Invalid benchmark node ID: {node}")
        nodes.append(node)
    return tuple(nodes)


def parse_protocol(data: bytes) -> Protocol:
    """Validate the complete protocol before starting any measurements."""
    payload = read_json(data)
    expected = set(Protocol.__dataclass_fields__) | {"schema_version"}
    if set(payload) != expected or type(payload["schema_version"]) is not int:
        fail("Protocol fields must match schema 1 exactly")
    if payload["schema_version"] != 1:
        fail("Unsupported protocol schema")
    targets, protected = node_ids(payload["targets"]), node_ids(payload["protected"])
    cells = targets + protected
    if len(cells) > MAX_CELLS or len(set(cells)) != len(cells):
        fail("Declare at most 32 distinct, non-overlapping node IDs")
    gain = bounded_number(payload, "practical_gain_floor", 1)
    spread = bounded_number(payload, "baseline_spread_ceiling", 0.25)
    if not gain or not spread:
        fail("Gain floor and spread ceiling must be positive")
    rationale = payload["gain_rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        fail("A workload-specific gain rationale is required")
    return Protocol(
        targets=targets,
        protected=protected,
        practical_gain_floor=gain,
        allowed_regression=bounded_number(payload, "allowed_regression", 0.25),
        baseline_spread_ceiling=spread,
        pair_count=count(payload, "pair_count", 5, 20),
        calibration_count=count(payload, "calibration_count", 3, 10),
        process_timeout_seconds=count(payload, "process_timeout_seconds", 1, 600),
        maximum_seconds=count(payload, "maximum_seconds", 60, 4200),
        plan_path=relative_path(payload["plan_path"]),
        gain_rationale=rationale,
    )


def parse_benchmarks(path: Path, cells: Sequence[str]) -> dict[str, float]:
    """Read all raw rounds, rejecting partial, duplicate and unexpected cells."""
    entries = read_json(path.read_bytes()).get("benchmarks")
    if not isinstance(entries, list):
        fail("Raw benchmark entries are missing")
    result: dict[str, float] = {}
    for value in entries:
        entry = object_value(value)
        node = entry.get("fullname")
        if not isinstance(node, str) or node not in cells or node in result:
            fail(f"Unexpected or duplicate benchmark cell: {node}")
        stats = object_value(entry.get("stats"))
        data = stats.get("data")
        if not isinstance(data, list) or len(data) < MIN_ROUNDS or stats.get("rounds") != len(data):
            fail(f"Missing full round data for {node}; use --benchmark-save-data")
        values = [number(sample) for sample in data]
        if min(values) <= 0:
            fail("Round times must be positive")
        result[node] = statistics.median(values)
    if set(result) != set(cells):
        fail(f"Missing benchmark cells: {sorted(set(cells) - set(result))}")
    return result


def spread(values: Sequence[float]) -> float:
    """Measure the full process-median range relative to its median."""
    return (max(values) - min(values)) / statistics.median(values)


def analyze_cell(
    protocol: Protocol,
    node: str,
    calibration: Sequence[float],
    baseline: Sequence[float],
    candidate: Sequence[float],
) -> dict[str, object]:
    """Apply fixed rules to one cell without executing or changing a subject."""
    throughput_ratios = [a / b for a, b in zip(baseline, candidate, strict=True)]
    time_ratios = [b / a for a, b in zip(baseline, candidate, strict=True)]
    gains = [ratio - 1 for ratio in throughput_ratios]
    regressions = [ratio - 1 for ratio in time_ratios]
    series = {"calibration": calibration, "baseline": baseline, "candidate": candidate}
    spreads = {name: spread(values) for name, values in series.items()}
    noise = max(spreads["calibration"], spreads["baseline"])
    status = "inconclusive"
    reason = "uncertainty crosses the declared boundary"
    # Compare ratios before subtracting one. This preserves inclusive fixed boundaries
    # such as 1.02 <= 1 + 0.02 without adding an undeclared numeric tolerance.
    if any(
        max(values) > min(values) + protocol.baseline_spread_ceiling * statistics.median(values)
        for values in series.values()
    ):
        reason = "process spread exceeds the declared ceiling"
    elif node in protocol.targets:
        boundary = max(protocol.practical_gain_floor, noise)
        if statistics.median(throughput_ratios) > 1 + boundary and min(throughput_ratios) > 1:
            status, reason = (
                "accepted",
                "median gain exceeds floor and noise; lower bound is positive",
            )
        elif statistics.median(throughput_ratios) <= 1 + protocol.practical_gain_floor:
            status, reason = "rejected", "no practical target gain"
    elif max(time_ratios) <= 1 + protocol.allowed_regression:
        status, reason = "accepted", "all paired regressions are within tolerance"
    elif min(time_ratios) > 1 + protocol.allowed_regression:
        status, reason = "rejected", "protected regression exceeds tolerance"
    return {
        "status": status,
        "reason": reason,
        "role": "target" if node in protocol.targets else "protected",
        "calibration_seconds": list(calibration),
        "baseline_seconds": list(baseline),
        "candidate_seconds": list(candidate),
        "spread": spreads,
        "observed_noise": noise,
        "baseline_median_seconds": statistics.median(baseline),
        "candidate_median_seconds": statistics.median(candidate),
        "baseline_median_ops": statistics.median([1 / value for value in baseline]),
        "candidate_median_ops": statistics.median([1 / value for value in candidate]),
        "pair_wins": sum(gain > 0 for gain in gains),
        "pair_count": len(gains),
        "paired_throughput_effects": gains,
        "paired_time_effects": regressions,
        "median_throughput_effect": statistics.median(gains),
        "median_time_effect": statistics.median(regressions),
        "throughput_interval": [min(gains), max(gains)],
        "time_interval": [min(regressions), max(regressions)],
        "median_interval_coverage_under_independence": 1 - 2 ** (1 - len(gains)),
    }


def analyze(
    protocol: Protocol,
    calibration: Sequence[Mapping[str, float]],
    pairs: Sequence[tuple[Mapping[str, float], Mapping[str, float]]],
    *,
    identical_source: bool = False,
) -> dict[str, object]:
    """Classify a complete matrix. Missing or invalid measurements are errors."""
    if len(calibration) != protocol.calibration_count or len(pairs) != protocol.pair_count:
        fail("Incomplete calibration or pair count")
    samples = [*calibration, *(sample for pair in pairs for sample in pair)]
    for sample in samples:
        if set(sample) != set(protocol.cells) or any(number(v) <= 0 for v in sample.values()):
            fail("Missing cells or invalid process medians")
    cells = {
        node: analyze_cell(
            protocol,
            node,
            [run[node] for run in calibration],
            [a[node] for a, _ in pairs],
            [b[node] for _, b in pairs],
        )
        for node in protocol.cells
    }
    statuses = {cell["status"] for cell in cells.values()}
    status = "accepted"
    if "inconclusive" in statuses:
        status = "inconclusive"
    elif "rejected" in statuses or identical_source:
        status = "rejected"
    return {
        "status": status,
        "cells": cells,
        "identical_source": identical_source,
        "reason": "identical source cannot establish a gain"
        if identical_source
        else "all targets and protected cells must pass",
    }


def sha256(data: bytes) -> str:
    """Hash immutable inputs and retained evidence."""
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: object) -> None:
    """Write a JSON evidence record."""
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def git(repo: Path, *arguments: str) -> bytes:
    """Run bounded read-only git commands with separate arguments, without a shell."""
    return subprocess.check_output(  # noqa: S603 - fixed executable and separate arguments
        [shutil.which("git") or "/usr/bin/git", "-C", str(repo), *arguments],
        timeout=60,
    )


def committed_file(repo: Path, revision: str, path: str) -> bytes:
    """Read a regular file from an exact commit; reject symlinks and trees."""
    relative_path(path)
    entry = git(repo, "ls-tree", revision, "--", path).decode()
    if not entry.startswith(("100644 blob ", "100755 blob ")):
        fail(f"Expected a committed regular file: {path}")
    return git(repo, "show", f"{revision}:{path}")


def unpack(data: bytes, destination: Path, *, harness_only: bool = False) -> None:
    """Extract only plain archive files into a newly owned directory."""
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            name = relative_path(member.name.rstrip("/"))
            if harness_only and (name == SUBJECT or name.startswith(f"{SUBJECT}/")):
                continue
            if member.isdir():
                continue
            if not member.isfile():
                fail(f"Archive contains a non-regular file: {name}")
            content = archive.extractfile(member)
            if content is None:
                fail(f"Cannot read archive member: {name}")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content.read())
            target.chmod(member.mode & 0o777)


def fingerprint(root: Path) -> dict[str, str]:
    """Hash every subject file, rejecting symlinks and recording relative paths."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            fail(f"Unexpected symlink: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return result


def verify_binding(subject: Path) -> dict[str, str]:
    """Reject controller installs and mixed imports, including package search paths."""
    expected = (subject / SUBJECT).resolve()
    result: dict[str, str] = {}
    for name, module in tuple(sys.modules.items()):
        if name != "diwire" and not name.startswith("diwire."):
            continue
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str) or not Path(origin).resolve().is_relative_to(expected):
            fail(f"Import misbinding: {name} from {origin}; expected {expected}")
        for package_path in getattr(module, "__path__", ()):
            if not Path(package_path).resolve().is_relative_to(expected):
                fail(f"Package path misbinding: {name} from {package_path}")
        result[name] = str(Path(origin).resolve())
    if "diwire" not in result:
        fail("The subject diwire package was not imported")
    return result


def runtime_metadata() -> dict[str, object]:
    """Record the common interpreter and installed dependency metadata hashes."""
    distributions = sorted(
        (
            dist.metadata["Name"],
            dist.version,
            sha256((dist.read_text("METADATA") or "").encode()),
            sha256((dist.read_text("RECORD") or "").encode()),
            dist.read_text("direct_url.json"),
        )
        for dist in importlib.metadata.distributions()
    )
    return {
        "executable": sys.executable,
        "version": sys.version,
        "executable_sha256": sha256(Path(sys.executable).resolve().read_bytes()),
        "python_flags": str(sys.flags),
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "platform": platform.platform(),
        "distributions": distributions,
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
    }


class BindingGuard:
    """Check imports inside each pytest process, before and after test execution."""

    def __init__(self, subject: Path) -> None:
        self.subject = subject

    def pytest_configure(self) -> None:
        """Check before collection."""
        verify_binding(self.subject)

    def pytest_runtest_setup(self) -> None:
        """Check before every selected cell."""
        verify_binding(self.subject)

    def pytest_sessionfinish(self) -> None:
        """Check after the final test and fixture cleanup."""
        verify_binding(self.subject)


def worker(subject: Path, raw: Path, cells: Sequence[str]) -> int:
    """Run pytest in this fresh isolated interpreter with verified subject imports."""
    sys.dont_write_bytecode = True
    if sys.flags.hash_randomization:
        fail("Workers require PYTHONHASHSEED=0")
    sys.path[:0] = [str(subject / "src"), str(subject)]
    __import__("diwire")
    binding_path = raw.with_suffix(".binding.json")
    metadata = runtime_metadata()
    initial_binding = verify_binding(subject)
    save(binding_path, {"initial_binding": initial_binding, "runtime": metadata})
    pytest = __import__("pytest")
    code = int(
        pytest.main(
            [
                *cells,
                "-q",
                "-o",
                "addopts=",
                "-o",
                "pythonpath=",
                "-p",
                "no:cacheprovider",
                "--benchmark-only",
                "--benchmark-save-data",
                f"--benchmark-json={raw}",
                f"--benchmark-storage={raw.parent / 'storage'}",
            ],
            plugins=[BindingGuard(subject)],
        )
    )
    save(
        binding_path,
        {
            "initial_runtime": metadata,
            "initial_binding": initial_binding,
            "runtime": runtime_metadata(),
            "final_binding": verify_binding(subject),
            "pytest_exit": code,
        },
    )
    return code


def optional_read(path: Path) -> str:
    """Read transient kernel files without treating process exit as measurement failure."""
    try:
        return path.read_text()
    except OSError as error:
        return f"unavailable: {type(error).__name__}"


def snapshot() -> dict[str, object]:
    """Record available Linux CPU, scheduler, power and process evidence."""
    paths = [
        Path(name)
        for name in (
            "/proc/cpuinfo",
            "/proc/stat",
            "/proc/loadavg",
            "/proc/meminfo",
            "/proc/self/status",
            "/sys/fs/cgroup/cpu.stat",
            "/sys/fs/cgroup/cpu.max",
        )
    ]
    paths.extend(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"))
    paths.extend(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_cur_freq"))
    return {
        "time_ns": time.time_ns(),
        "platform": platform.platform(),
        "power_state": "Hosted VM; host power policy unavailable",
        "files": {str(path): optional_read(path) for path in paths},
        "processes": {
            str(path.parent): optional_read(path)
            for path in Path("/proc").glob("[0-9]*/stat")
            if path.is_file()
        },
    }


@dataclass
class Runner:
    """Execute a fixed process sequence and retain partial evidence on failure."""

    protocol: Protocol
    output: Path
    subjects: dict[str, Path]
    manifests: dict[str, dict[str, str]]
    deadline: float
    runtime: dict[str, object] | None = None

    def measure(self, label: str, role: str) -> dict[str, float]:
        """Run one fresh process. Do not retry or overwrite its artifacts."""
        subject = self.subjects[role]
        raw = self.output / f"{label}-{role}.json"
        command = [
            sys.executable,
            "-P",
            "-s",
            str(Path(__file__).resolve()),
            "--worker",
            str(subject),
            str(raw),
            *self.protocol.cells,
        ]
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            fail("Measurement budget exhausted")
        save(
            raw.with_suffix(".command.json"),
            {"command": command, "cwd": str(subject), "before": snapshot()},
        )
        environment = dict(os.environ)
        for key in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
        ):
            environment.pop(key, None)
        environment.update(PYTHONHASHSEED="0", DIWIRE_BENCHMARK_POWER_STATE="Hosted Linux VM")
        with raw.with_suffix(".log").open("w") as log:
            process = subprocess.run(  # noqa: S603 - no shell, fixed interpreter and argument list
                command,
                cwd=subject,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=min(remaining, self.protocol.process_timeout_seconds),
                check=False,
            )
        save(raw.with_suffix(".after.json"), snapshot())
        if fingerprint(subject) != self.manifests[role]:
            fail(f"Subject files changed during measurement: {role}")
        if process.returncode:
            fail(f"Measurement failed ({process.returncode}); see {raw.with_suffix('.log')}")
        binding = read_json(raw.with_suffix(".binding.json").read_bytes())
        current = object_value(binding["runtime"])
        if current != binding["initial_runtime"] or (self.runtime and self.runtime != current):
            fail("Runtime or dependency metadata changed between measurements")
        self.runtime = current
        return parse_benchmarks(raw, self.protocol.cells)

    def run(self) -> dict[str, object]:
        """Run calibration and all alternating pairs exactly once."""
        calibration = [
            self.measure(f"calibration-{index:02}", "base")
            for index in range(self.protocol.calibration_count)
        ]
        pairs: list[tuple[dict[str, float], dict[str, float]]] = []
        for index in range(self.protocol.pair_count):
            order = ("base", "next") if index % 2 == 0 else ("next", "base")
            values = {role: self.measure(f"pair-{index:02}", role) for role in order}
            pairs.append((values["base"], values["next"]))
        for role, subject in self.subjects.items():
            if fingerprint(subject) != self.manifests[role]:
                fail(f"Subject files changed before analysis: {role}")
        identical = fingerprint(self.subjects["base"] / SUBJECT) == fingerprint(
            self.subjects["next"] / SUBJECT,
        )
        return analyze(self.protocol, calibration, pairs, identical_source=identical)


def check_inputs(repo: Path, args: argparse.Namespace) -> None:
    """Require immutable commits, a clean controller and unchanged dependencies."""
    for revision in (args.base_sha, args.candidate_sha):
        if not SHA_PATTERN.fullmatch(revision):
            fail("Commit inputs must be full lowercase 40-character SHAs")
        if (
            git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
            != revision
        ):
            fail("Commit did not resolve to the exact supplied SHA")
    if git(repo, "rev-parse", "HEAD").decode().strip() != args.candidate_sha:
        fail("Controller HEAD must be the exact candidate SHA")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        fail("Controller tracked files must be clean")
    if platform.system() != "Linux" or platform.python_version() != PYTHON_VERSION:
        fail("Require Linux with CPython 3.14.7")
    for path in ("uv.lock", "pyproject.toml"):
        candidate = committed_file(repo, args.candidate_sha, path)
        if candidate != committed_file(repo, args.base_sha, path):
            fail(f"Runtime dependencies/configuration differ: {path}")
        if (repo / path).read_bytes() != candidate:
            fail(f"Controller dependency file differs: {path}")


def prepare(repo: Path, output: Path, args: argparse.Namespace) -> Runner:
    """Freeze committed subjects, protocol, plan and manifests before timing."""
    check_inputs(repo, args)
    protocol_data = committed_file(repo, args.candidate_sha, args.protocol)
    (output / "protocol.json").write_bytes(protocol_data)
    protocol = parse_protocol(protocol_data)
    plan = committed_file(repo, args.candidate_sha, protocol.plan_path)
    (output / "plan.txt").write_bytes(plan)
    if protocol.gain_rationale.encode() not in plan:
        fail("The committed plan must contain the workload-specific gain rationale verbatim")
    archive = git(repo, "archive", "--format=tar", args.candidate_sha)
    baseline = git(repo, "archive", "--format=tar", args.base_sha, "--", SUBJECT)
    (output / "candidate.tar").write_bytes(archive)
    (output / "base-source.tar").write_bytes(baseline)
    subjects = {role: output / "subjects" / role for role in ("base", "next")}
    for role, root in subjects.items():
        root.mkdir(parents=True)
        unpack(archive, root, harness_only=role == "base")
        if role == "base":
            unpack(baseline, root)
    manifests = {role: fingerprint(root) for role, root in subjects.items()}
    harnesses = [
        {name: digest for name, digest in manifest.items() if not name.startswith(f"{SUBJECT}/")}
        for manifest in manifests.values()
    ]
    if harnesses[0] != harnesses[1]:
        fail("Frozen candidate harnesses differ")
    save(
        output / "inputs.json",
        {
            "base_sha": args.base_sha,
            "candidate_sha": args.candidate_sha,
            "protocol_path": args.protocol,
            "protocol_sha256": sha256(protocol_data),
            "plan_path": protocol.plan_path,
            "plan_sha256": sha256(plan),
            "candidate_archive_sha256": sha256(archive),
            "base_archive_sha256": sha256(baseline),
            "uv_lock_sha256": sha256((repo / "uv.lock").read_bytes()),
            "controller_sha256": sha256(Path(__file__).read_bytes()),
            "manifests": manifests,
            "runtime": runtime_metadata(),
            "initial_machine": snapshot(),
        },
    )
    return Runner(
        protocol, output, subjects, manifests, time.monotonic() + protocol.maximum_seconds
    )


class ArgumentParser(argparse.ArgumentParser):
    """Use the documented error exit code for command-line errors too."""

    def error(self, message: str) -> NoReturn:
        """Report usage errors as execution errors."""
        self.exit(EXIT_CODES["error"], f"{message}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Compare exact commits and retain an auditable final or partial decision."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--worker":
        return worker(Path(arguments[1]), Path(arguments[2]), arguments[3:])
    parser = ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(arguments)
    output = cast("Path", args.output).resolve()
    # Refuse existing paths. Never remove, clean or restore caller-owned files.
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        sys.stderr.write(f"Cannot create new evidence directory: {error}\n")
        return EXIT_CODES["error"]
    decision: dict[str, object] = {
        "schema_version": 1,
        "status": "error",
        "reason": "comparison did not finish",
        "base_sha": args.base_sha,
        "candidate_sha": args.candidate_sha,
        "protocol_path": args.protocol,
        "command": [sys.executable, "-m", "tools.bb_perf_compare", *arguments],
    }
    save(output / "decision.json", decision)
    try:
        runner = prepare(args.repo.resolve(), output, args)
        decision.update(runner.run())
    except (
        ComparisonError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        tarfile.TarError,
        KeyboardInterrupt,
    ) as error:
        decision.update(status="error", reason=f"{type(error).__name__}: {error}")
    finally:
        if (output / "protocol.json").is_file():
            decision["protocol_sha256"] = sha256((output / "protocol.json").read_bytes())
        if (output / "inputs.json").is_file():
            decision["inputs"] = read_json((output / "inputs.json").read_bytes())
        decision["evidence_sha256"] = {
            str(path.relative_to(output)): sha256(path.read_bytes())
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "decision.json"
        }
        save(output / "decision.json", decision)
    return EXIT_CODES[str(decision["status"])]


if __name__ == "__main__":
    raise SystemExit(main())
