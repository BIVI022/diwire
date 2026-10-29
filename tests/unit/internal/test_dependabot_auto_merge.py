from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / ".github/scripts/merge-dependabot.sh"
_HEAD_SHA = "a" * 40
_BASE_SHA = "b" * 40
_FAKE_GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["GH_CALL_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
scenario = os.environ["GH_SCENARIO"]
if args[:2] == ["run", "list"]:
    workflow = args[args.index("--workflow") + 1]
    if scenario != "missing" and not (scenario == "docs-missing" and workflow == "docs.yaml"):
        print("456" if workflow == "docs.yaml" else "123")
elif args[:2] == ["run", "watch"]:
    sys.exit(1 if scenario == "failed" or (scenario == "docs-failed" and args[2] == "456") else 0)
elif args[:2] == ["pr", "view"]:
    print("c" * 40 if scenario == "head-changed" else os.environ["PR_HEAD_SHA"])
elif args[0] == "api":
    print("c" * 40 if scenario == "base-changed" else os.environ["PR_BASE_SHA"])
elif args[:2] != ["pr", "merge"]:
    sys.exit(2)
"""


def _run_merge(tmp_path: Path, scenario: str) -> tuple[int, list[list[str]]]:
    gh = tmp_path / "gh"
    gh.write_text(_FAKE_GH)
    gh.chmod(0o700)
    log = tmp_path / "calls.jsonl"
    environment = os.environ.copy()
    environment.update(
        PATH=f"{tmp_path}{os.pathsep}{environment['PATH']}",
        GH_CALL_LOG=str(log),
        GH_SCENARIO=scenario,
        GH_REPO="owner/diwire",
        PR_URL="https://github.com/owner/diwire/pull/1",
        PR_HEAD_SHA=_HEAD_SHA,
        PR_BASE_SHA=_BASE_SHA,
        MERGE_WAIT_ATTEMPTS="1",
        MERGE_WAIT_SECONDS="0",
    )
    # Run only the local script with a test-owned gh stub.
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result.returncode, calls


@pytest.mark.parametrize(
    "scenario", ["failed", "missing", "docs-failed", "docs-missing", "head-changed", "base-changed"]
)
def test_dependabot_does_not_merge_without_successful_current_checks(
    tmp_path: Path, scenario: str
) -> None:
    returncode, calls = _run_merge(tmp_path, scenario)

    assert returncode != 0
    assert all(call[:2] != ["pr", "merge"] for call in calls)


def test_dependabot_waits_for_ci_and_docs_before_merging_exact_head(tmp_path: Path) -> None:
    returncode, calls = _run_merge(tmp_path, "success")

    assert returncode == 0
    lists = [call for call in calls if call[:2] == ["run", "list"]]
    assert [call[call.index("--workflow") + 1] for call in lists] == ["ci.yaml", "docs.yaml"]
    assert all(call[call.index("--commit") + 1] == _HEAD_SHA for call in lists)
    watches = [call for call in calls if call[:2] == ["run", "watch"]]
    assert len(watches) == 2
    assert all("--exit-status" in call for call in watches)
    assert calls[-1][:2] == ["pr", "merge"]
    assert "--auto" not in calls[-1]
    assert calls[-1][calls[-1].index("--match-head-commit") + 1] == _HEAD_SHA
