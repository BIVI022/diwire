from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.bb_perf_dispatch import (
    Controller,
    DispatchError,
    Job,
    main,
    obj,
    parser,
    patch_version,
)


class Fake:
    def __init__(self, tmp_path: Path) -> None:
        self.now = datetime(2026, 10, 27, 6, tzinfo=timezone.utc)
        self.config = tmp_path / "config.json"
        self.state = tmp_path / "state"
        self.workspace = tmp_path / "worker"
        self.workspace.mkdir()
        for name in ("DAILY", "FOLLOWUP", "RELEASE"):
            (tmp_path / f"{name}.md").write_text(f"{name} prompt")
        self.config.write_text(
            json.dumps(
                {
                    "project_id": "proj_hypmgayr8j",
                    "repository": "maksimzayats/diwire",
                    "checkout": str(tmp_path),
                    "prompt_directory": str(tmp_path),
                    "provider": "codex",
                    "model": "model",
                    "reasoning": "high",
                }
            )
        )
        self.calls: list[list[str]] = []
        self.threads: list[dict[str, object]] = []
        self.interrupt = False
        self.provisioning = False
        self.fail_before_create = False
        self.review_body = "Initial review"
        self.head = "abc"
        self.merged = False
        self.ci = "success"
        self.postmerge = "success"
        self.workflow_paths = [".github/workflows/ci.yaml", ".github/workflows/docs.yaml"]
        self.controller = Controller(
            self.config, self.state, runner=self.run, clock=lambda: self.now
        )

    def run(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[0] == "git":
            return ""
        if argv[:3] == ["bb", "thread", "list"]:
            return json.dumps([] if "--archived" in argv else self.threads)
        if argv[:3] == ["bb", "thread", "spawn"]:
            return self.spawn(argv)
        if argv[:3] == ["bb", "thread", "show"]:
            thread = next(thread for thread in self.threads if thread["id"] == argv[3])
            return json.dumps(
                {
                    "thread": thread,
                    "environment": None
                    if self.provisioning
                    else {"id": "env_1", "path": str(self.workspace)},
                }
            )
        if argv[:3] == ["gh", "api", "graphql"]:
            return json.dumps(
                [
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "review",
                                                "isResolved": False,
                                                "comments": {
                                                    "nodes": [{"body": self.review_body}],
                                                    "pageInfo": {"hasNextPage": False},
                                                },
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                ]
            )
        if argv[:2] == ["gh", "api"]:
            return self.gh(argv)
        raise AssertionError(argv)

    def spawn(self, argv: list[str]) -> str:
        if self.fail_before_create:
            raise subprocess.TimeoutExpired(argv, 55)
        thread: dict[str, object] = {
            "id": f"thr_{len(self.threads)}",
            "title": argv[argv.index("--title") + 1],
            "environmentId": "env_1",
            "projectId": "proj_hypmgayr8j",
            "status": "active",
        }
        self.threads.append(thread)
        if self.interrupt:
            self.interrupt = False
            raise subprocess.TimeoutExpired(argv, 55)
        return json.dumps(thread)

    def gh(self, argv: list[str]) -> str:
        endpoint = argv[-1]
        if "/git/commits/" in endpoint:
            return json.dumps(
                {"tree": {"sha": "accepted-tree"}, "parents": [{"sha": "accepted-base"}]}
            )
        if endpoint.endswith("/pulls/42"):
            return json.dumps(
                {
                    "head": {"sha": self.head},
                    "merged": self.merged,
                    "merge_commit_sha": "merged-sha",
                }
            )
        if "/check-runs?" in endpoint:
            return json.dumps([{"check_runs": [{"conclusion": self.ci}]}])
        if "/statuses?" in endpoint:
            return "[[]]"
        if "/actions/runs?" in endpoint:
            return json.dumps(
                [
                    {
                        "workflow_runs": [
                            {
                                "head_sha": "merged-sha",
                                "head_branch": "main",
                                "event": "push",
                                "path": path,
                                "status": "completed",
                                "conclusion": self.postmerge,
                            }
                            for path in self.workflow_paths
                        ]
                    }
                ]
            )
        return "[[]]"

    def jobs(self) -> dict[str, Job]:
        with self.controller.store.locked():
            return self.controller.store.state["jobs"]

    def job(self) -> Job:
        return self.jobs()["daily:2026-10-27"]

    def spawns(self) -> list[list[str]]:
        return [call for call in self.calls if call[:3] == ["bb", "thread", "spawn"]]

    def record(self, status: str, **kwargs: str) -> None:
        job = self.job()
        argv = [
            "--config",
            str(self.config),
            "--state-dir",
            str(self.state),
            "record",
            "--job",
            job["id"],
            "--thread-id",
            job["thread_id"],
            "--environment-id",
            "env_1",
            "--workspace",
            str(self.workspace),
            "--status",
            status,
        ]
        for key, value in kwargs.items():
            argv.extend(["--" + key.replace("_", "-"), value])
        self.controller.record(parser().parse_args(argv))

    def waiting(self) -> None:
        self.controller.tick()
        self.record(
            "waiting_review",
            pr="42",
            head_sha="abc",
            validation_evidence="/evidence.json",
            measurement_run_url="https://ci/run/1",
        )
        self.threads[-1]["status"] = "idle"

    def complete(self, *, non_runtime: bool = False) -> None:
        evidence = self.workspace / "validation.json"
        evidence.write_text("{}")
        if non_runtime:
            evidence = _non_runtime_evidence(self)
        job = self.job()
        argv = [
            "--config",
            str(self.config),
            "--state-dir",
            str(self.state),
            "record",
            "--job",
            job["id"],
            "--thread-id",
            job["thread_id"],
            "--environment-id",
            job["environment_id"],
            "--workspace",
            job["workspace"],
            "--status",
            "complete",
            "--reason",
            "Verified merge",
            "--validation-evidence",
            str(evidence),
            "--measurement-run-url",
            "https://ci/run/1",
        ]
        for receipt in (
            f"accepted_head_sha={self.head}",
            "accepted_base_sha=accepted-base",
            "accepted_tree_sha=accepted-tree",
            "merge_sha=merged-sha",
        ):
            argv.extend(["--receipt", receipt])
        if non_runtime:
            argv.extend(["--receipt", "change_kind=non_runtime"])
            index = argv.index("--measurement-run-url")
            del argv[index : index + 2]
        self.controller.record(parser().parse_args(argv))


@pytest.fixture()
def fake(tmp_path: Path) -> Fake:
    return Fake(tmp_path)


def test_duplicate_tick_uses_fresh_visible_worktree_without_old_chat(fake: Fake) -> None:
    fake.controller.tick()
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    argv = fake.spawns()[0]
    assert argv[argv.index("--project") + 1] == "proj_hypmgayr8j"
    assert argv[argv.index("--new-environment") + 1] == "worktree"
    assert argv[argv.index("--base-branch") + 1] == "origin/main"
    assert argv[argv.index("--visibility") + 1] == "visible"
    assert "--target-thread" not in argv
    assert "--environment" not in argv
    assert fake.calls.index(
        next(call for call in fake.calls if call[0] == "git")
    ) < fake.calls.index(argv)
    prompt = Path(argv[argv.index("--prompt-file") + 1]).read_text()
    assert "daily:2026-10-27" in prompt
    assert '"record_command"' in prompt
    assert fake.job()["environment_id"] == "env_1"


def test_interrupted_dispatch_reconciles_before_retry(fake: Fake) -> None:
    fake.interrupt = True
    with pytest.raises(subprocess.TimeoutExpired):
        fake.controller.tick()
    assert fake.job()["intent"]
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    assert not fake.job()["intent"]


def test_missing_environment_does_not_provision_a_second_thread(fake: Fake) -> None:
    fake.provisioning = True
    fake.controller.tick()
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    assert fake.job()["intent"]
    assert not fake.job()["environment_id"]
    fake.provisioning = False
    fake.controller.tick()
    assert fake.job()["environment_id"] == "env_1"


def test_unknown_result_retries_are_bounded(fake: Fake) -> None:
    fake.fail_before_create = True
    for _ in range(3):
        with pytest.raises(subprocess.TimeoutExpired):
            fake.controller.tick()
    fake.controller.tick()
    assert fake.job()["status"] == "blocked"
    assert fake.job()["recoveries"] == 2
    assert len(fake.spawns()) == 3
    fake.controller.tick()
    assert len(fake.spawns()) == 3


def test_review_body_change_waits_ten_minutes_then_opens_new_root(fake: Fake) -> None:
    fake.waiting()
    fake.review_body = "Please fix the cleanup regression"
    fake.now += timedelta(minutes=9)
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    fake.now += timedelta(minutes=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    followup = fake.spawns()[-1]
    assert "--new-environment" not in followup
    assert followup[followup.index("--environment") + 1] == "env_1"
    assert "FOLLOWUP prompt" in Path(followup[followup.index("--prompt-file") + 1]).read_text()


def test_first_wait_gets_one_followup_then_unchanged_snapshot_does_not_wake(fake: Fake) -> None:
    fake.waiting()
    fake.now += timedelta(minutes=11)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    fake.record("waiting_review", pr="42", head_sha="abc")
    fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(minutes=11)
    for _ in range(3):
        fake.controller.tick()
    assert len(fake.spawns()) == 2


@pytest.mark.parametrize("change", ["head", "ci"])
def test_head_or_failed_ci_can_wake_before_review_wait(fake: Fake, change: str) -> None:
    fake.waiting()
    if change == "head":
        fake.head = "new-head"
    else:
        fake.ci = "failure"
    fake.now += timedelta(seconds=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert fake.job()["head_sha"] == fake.head


def test_active_thread_prevents_followup_and_next_day_overlap(fake: Fake) -> None:
    fake.waiting()
    fake.threads[-1]["status"] = "active"
    fake.head = "new-head"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    assert fake.jobs()["daily:2026-10-28"]["status"] == "queued"


def test_interrupted_pre_pr_owner_recovers_in_same_worktree(fake: Fake) -> None:
    fake.controller.tick()
    fake.threads[-1]["status"] = "error"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert fake.job()["status"] == "running"
    assert fake.job()["recoveries"] == 1
    assert "--environment" in fake.spawns()[-1]
    assert "same worktree" in str(fake.job()["receipts"][-2]["reason"])
    assert fake.jobs()["daily:2026-10-28"]["status"] == "queued"


def test_blocked_release_does_not_block_unrelated_daily(fake: Fake) -> None:
    fake.controller.tick()
    fake.record("blocked", reason="Release blocker #298")
    fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 2


def test_deadline_recoveries_are_bounded(fake: Fake) -> None:
    fake.waiting()
    for attempt in range(2):
        fake.now += timedelta(days=1)
        fake.controller.tick()
        assert fake.job()["recoveries"] == attempt + 1
        fake.record("waiting_review", pr="42", head_sha="abc")
        fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert fake.job()["status"] == "blocked"
    assert fake.job()["recoveries"] == 2


def test_external_merge_requires_postmerge_success(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    fake.postmerge = "failure"
    fake.controller.tick()
    assert fake.job()["status"] != "complete"
    fake.postmerge = "success"
    fake.controller.tick()
    assert fake.job()["status"] != "complete"
    fake.now += timedelta(minutes=10)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert fake.job()["status"] == "running"
    assert "reconciliation" in str(fake.job()["receipts"][-2]["reason"])


def test_stale_owner_and_terminal_receipts_are_rejected(fake: Fake) -> None:
    fake.waiting()
    fake.head = "new-head"
    fake.controller.tick()
    with pytest.raises(DispatchError, match="Stale"):
        fake.record("blocked", thread_id="thr_0", reason="wrong owner")
    fake.record("rejected", reason="Measured regression")
    with pytest.raises(DispatchError, match="Terminal"):
        fake.record("running")


def test_complete_requires_proof_and_exact_head(fake: Fake) -> None:
    fake.controller.tick()
    with pytest.raises(DispatchError, match="validation evidence"):
        fake.record("complete", reason="done")
    with pytest.raises(DispatchError, match="validation evidence"):
        fake.record(
            "complete",
            pr="42",
            head_sha="old",
            validation_evidence="/proof.json",
            measurement_run_url="https://ci/run/1",
            reason="done",
        )


def test_monday_release_defers_until_daily_writer_ends(fake: Fake) -> None:
    fake.now = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    assert fake.jobs()["release:2026-W45"]["status"] == "queued"
    with fake.controller.store.locked():
        daily = fake.controller.store.state["jobs"]["daily:2026-11-02"]
        daily["status"] = "inconclusive"
        fake.controller.store.save()
    fake.threads[-1]["status"] = "idle"
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert (
        "RELEASE prompt"
        in Path(fake.spawns()[-1][fake.spawns()[-1].index("--prompt-file") + 1]).read_text()
    )
    fake.controller.tick()
    assert len(fake.spawns()) == 2


def test_schedule_override_and_dry_run_do_not_dispatch(fake: Fake) -> None:
    config = obj(json.loads(fake.config.read_text()))
    config["daily_time"] = "10:00"
    fake.config.write_text(json.dumps(config))
    controller = Controller(fake.config, fake.state, runner=fake.run, clock=lambda: fake.now)
    assert controller.tick(dry_run=True)["due"] == []
    fake.now += timedelta(hours=1)
    assert controller.tick(dry_run=True)["due"] == [("daily:2026-10-27", "daily")]
    assert not fake.calls
    assert not (fake.state / "state.json").exists()


def test_missing_prompt_fails_before_side_effects(fake: Fake) -> None:
    (fake.config.parent / "FOLLOWUP.md").unlink()
    with pytest.raises(DispatchError, match="Missing prompt"):
        Controller(fake.config, fake.state, runner=fake.run)
    assert not fake.calls


@pytest.mark.parametrize(("old", "expected"), [("v0.9.99", "v0.9.100"), ("v1.2.3", "v1.2.4")])
def test_patch_version_preserves_major_minor(old: str, expected: str) -> None:
    assert patch_version(old) == expected


@pytest.mark.parametrize("version", ["1.2.3", "v1.2", "v1.2.3rc1", "v01.2.3"])
def test_patch_version_rejects_ambiguous_tags(version: str) -> None:
    with pytest.raises(DispatchError, match=r"vX\.Y\.Z"):
        patch_version(version)


def test_cli_status_and_errors(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    prefix = ["--config", str(fake.config), "--state-dir", str(fake.state)]
    assert main([*prefix, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1
    assert main([*prefix, "tick", "--dry-run", "--now", "2026-10-27T09:00:00+03:00"]) == 0
    assert main([*prefix, "tick", "--dry-run", "--now", "2026-10-27T09:00:00"]) == 1
    assert "explicit UTC offset" in capsys.readouterr().err
    fake.config.write_text("{}")
    assert main([*prefix, "tick"]) == 1


def test_no_repeat_wake_for_the_same_failed_ci(fake: Fake) -> None:
    fake.waiting()
    fake.ci = "failure"
    fake.controller.tick()
    fake.record("waiting_ci", pr="42", head_sha="abc")
    fake.threads[-1]["status"] = "idle"
    fake.controller.tick()
    assert len(fake.spawns()) == 2


def test_new_day_can_start_after_verified_complete(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    fake.complete()
    assert fake.job()["status"] == "complete"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 2


def test_worker_that_ends_before_provisioning_does_not_lock_next_day(fake: Fake) -> None:
    fake.provisioning = True
    fake.controller.tick()
    fake.threads[0]["status"] = "error"
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert fake.job()["status"] == "blocked"
    assert "before environment provisioning" in fake.job()["reason"]
    assert len(fake.spawns()) == 2


def test_ambiguous_dispatch_reconciliation_never_spawns_again(fake: Fake) -> None:
    fake.interrupt = True
    with pytest.raises(subprocess.TimeoutExpired):
        fake.controller.tick()
    fake.threads.append({**fake.threads[0], "id": "other-thread"})
    with pytest.raises(DispatchError, match="Multiple threads"):
        fake.controller.tick()
    assert len(fake.spawns()) == 1


def test_changed_head_invalidates_saved_measurement_evidence(fake: Fake) -> None:
    fake.waiting()
    fake.head = "new-head"
    fake.controller.tick()
    fake.record("waiting_ci", head_sha="new-head")
    fake.threads[-1]["status"] = "idle"
    fake.merged = True
    fake.controller.tick()
    assert fake.job()["status"] != "complete"


def test_cli_refuses_time_travel_for_live_tick(
    fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "--config",
                str(fake.config),
                "--state-dir",
                str(fake.state),
                "tick",
                "--now",
                "2026-10-27T09:00:00+03:00",
            ]
        )
        == 1
    )
    assert "restricted" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("project_id", "other"),
        ("timezone", "UTC"),
        ("daily_time", "9:00"),
        ("max_recovery_attempts", 3),
        ("review_wait_seconds", 599),
        ("review_deadline_seconds", "86400"),
        ("unknown_field", 1),
    ],
)
def test_invalid_config_fails_before_any_tool_call(fake: Fake, key: str, value: object) -> None:
    config = obj(json.loads(fake.config.read_text()))
    config[key] = value
    fake.config.write_text(json.dumps(config))
    with pytest.raises(DispatchError):
        Controller(fake.config, fake.state, runner=fake.run)
    assert not fake.calls


def test_release_complete_checks_patch_publish_and_pypi_hashes(fake: Fake) -> None:
    evidence = fake.workspace / "release-proof.json"
    evidence.write_text("{}")
    args = parser().parse_args(
        [
            "--config",
            str(fake.config),
            "--state-dir",
            str(fake.state),
            "record",
            "--job",
            "release:2026-W45",
            "--thread-id",
            "root",
            "--environment-id",
            "env",
            "--workspace",
            str(fake.workspace),
            "--status",
            "complete",
            "--validation-evidence",
            str(evidence),
            "--reason",
            "published",
            "--receipt",
            "previous_version=v1.5.0",
            "--receipt",
            "release_version=v1.5.1",
            "--receipt",
            "release_url=https://release",
            "--receipt",
            "publish_run_id=123",
            "--receipt",
            "wheel_sha256=wheel",
            "--receipt",
            "sdist_sha256=sdist",
        ]
    )
    publish: dict[str, object] = {
        "status": "completed",
        "conclusion": "success",
        "head_branch": "v1.5.1",
        "head_sha": "tag-sha",
        "event": "release",
        "path": ".github/workflows/publish.yaml",
    }
    files: list[dict[str, object]] = [
        {"packagetype": "bdist_wheel", "yanked": False, "digests": {"sha256": "wheel"}},
        {"packagetype": "sdist", "yanked": False, "digests": {"sha256": "sdist"}},
    ]

    def release_api(argv: list[str]) -> str:
        endpoint = argv[-1]
        if "/releases/tags/" in endpoint:
            return json.dumps({"html_url": "https://release", "draft": False, "prerelease": False})
        if "/actions/runs?" in endpoint:
            return json.dumps(
                [
                    {
                        "workflow_runs": [
                            {
                                "head_sha": "tag-sha",
                                "head_branch": "main",
                                "event": "push",
                                "path": path,
                                "status": "completed",
                                "conclusion": "success",
                            }
                            for path in (".github/workflows/ci.yaml", ".github/workflows/docs.yaml")
                        ]
                    }
                ]
            )
        if "/actions/runs/" in endpoint:
            return json.dumps(publish)
        return json.dumps({"sha": "tag-sha"})

    fake.controller.run = release_api
    fake.controller.fetch = lambda _url: {"info": {"version": "1.5.1"}, "urls": files}
    fake.controller.release_complete(args)
    files[0]["digests"] = {"sha256": "bad"}
    with pytest.raises(DispatchError, match="hash"):
        fake.controller.release_complete(args)
    files[0]["digests"] = {"sha256": "wheel"}
    publish["head_sha"] = "wrong-sha"
    with pytest.raises(DispatchError, match="tag commit"):
        fake.controller.release_complete(args)
    publish["head_sha"] = "tag-sha"
    args.receipt[1] = "release_version=v1.6.0"
    with pytest.raises(DispatchError, match="PATCH"):
        fake.controller.release_complete(args)


def test_release_waits_for_publish_run_change_without_a_pr(fake: Fake) -> None:
    job = fake.controller.new_job("release:2026-W45", "release")
    with fake.controller.store.locked():
        fake.controller.store.state["jobs"][job["id"]] = job
        fake.controller.spawn(job)
        job["status"] = "waiting_ci"
        job["wait_since"] = fake.now.timestamp()
        fake.controller.receipt(job, "Publishing", receipts=["publish_run_id=123"])
        fake.controller.run = lambda _argv: json.dumps({"status": "in_progress"})
        job["digest"] = fake.controller.digest(fake.controller.release_snapshot(job))
        fake.controller.store.save()
    runner = fake.controller.run

    def finished(argv: list[str]) -> str:
        if argv[0] == "gh":
            return json.dumps({"status": "completed", "conclusion": "success"})
        return fake.run(argv)

    fake.controller.run = finished
    fake.controller.watch_release(job)
    assert len(fake.spawns()) == 1
    fake.now += timedelta(minutes=10)
    fake.controller.watch_release(job)
    assert len(fake.spawns()) == 2
    assert "--environment" in fake.spawns()[-1]


def test_idle_root_with_active_workflow_retains_writer_claim(fake: Fake) -> None:
    fake.controller.tick()
    fake.threads[0]["status"] = "idle"
    fake.threads[0]["activity"] = {"activeWorkflowCount": 1}
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 1
    assert fake.job()["status"] == "running"


def test_idle_root_with_queued_work_retains_writer_claim(fake: Fake) -> None:
    fake.controller.tick()
    fake.threads[0]["status"] = "idle"
    fake.threads[0]["queuedMessageCount"] = 1
    fake.now += timedelta(days=1)
    fake.controller.tick()
    assert len(fake.spawns()) == 1


def test_queued_monday_release_starts_on_tuesday_before_daily_schedule(fake: Fake) -> None:
    fake.now = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)
    fake.controller.tick()
    assert fake.jobs()["release:2026-W45"]["status"] == "queued"
    with fake.controller.store.locked():
        daily = fake.controller.store.state["jobs"]["daily:2026-11-02"]
        daily["status"] = "blocked"
        fake.controller.receipt(daily, "Concrete external blocker prevents both delivery paths")
        fake.controller.store.save()
    fake.threads[-1]["status"] = "idle"
    fake.now = datetime(2026, 11, 3, 5, tzinfo=timezone.utc)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert fake.jobs()["release:2026-W45"]["status"] == "running"
    assert fake.jobs()["release:2026-W45"]["date"] == "2026-11-02"


def test_feedback_arriving_between_followup_and_record_is_not_consumed(fake: Fake) -> None:
    fake.waiting()
    fake.now += timedelta(minutes=10)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    fake.review_body = "New feedback after followup inspected its snapshot"
    fake.record("waiting_review", pr="42", head_sha="abc")
    fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(minutes=10)
    fake.controller.tick()
    assert len(fake.spawns()) == 3


def test_head_changed_before_wait_record_is_not_consumed(fake: Fake) -> None:
    fake.controller.tick()
    fake.head = "new-head-before-record"
    fake.record("waiting_review", pr="42", head_sha="abc")
    fake.threads[-1]["status"] = "idle"
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert "invalidate" in str(fake.job()["receipts"][-2]["reason"])


@pytest.mark.parametrize(
    "paths",
    [
        [".github/workflows/docs.yaml"],
        [".github/workflows/ci.yaml"],
        [".github/workflows/unrelated.yaml"],
    ],
)
def test_postmerge_requires_both_actual_ci_and_docs(fake: Fake, paths: list[str]) -> None:
    fake.waiting()
    fake.merged = True
    fake.workflow_paths = paths
    fake.controller.tick()
    assert fake.job()["status"] != "complete"


def test_postmerge_uses_latest_attempt_of_each_required_workflow(fake: Fake) -> None:
    def runs(argv: list[str]) -> str:
        workflows: list[dict[str, object]] = [
            {
                "path": path,
                "head_sha": "merged-sha",
                "head_branch": "main",
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "run_number": 1,
                "run_attempt": 1,
            }
            for path in (".github/workflows/ci.yaml", ".github/workflows/docs.yaml")
        ]
        workflows.append({**workflows[0], "run_attempt": 2, "conclusion": "failure"})
        return json.dumps([{"workflow_runs": workflows}])

    fake.controller.run = runs
    assert not fake.controller.postmerge_ok({"merged": True, "merge_commit_sha": "merged-sha"})


@pytest.mark.parametrize("field", ["tree", "parents"])
def test_complete_rejects_merge_tree_or_base_mismatch(fake: Fake, field: str) -> None:
    fake.waiting()
    fake.merged = True

    def wrong_merge(argv: list[str]) -> str:
        value = fake.run(argv)
        if "/git/commits/merged-sha" in argv[-1]:
            commit = obj(json.loads(value))
            commit[field] = {"sha": "wrong-tree"} if field == "tree" else [{"sha": "wrong-base"}]
            return json.dumps(commit)
        return value

    fake.controller.run = wrong_merge
    with pytest.raises(DispatchError, match="Merged tree/base"):
        fake.complete()
    assert fake.job()["status"] != "complete"


def test_complete_rejects_a_head_that_differs_from_accepted_job(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    fake.head = "different-head"
    with pytest.raises(DispatchError, match="exact-head"):
        fake.complete()


def test_followup_context_shares_persisted_head_review_clock(fake: Fake) -> None:
    fake.waiting()
    observed = fake.job()["head_observed_at"]
    fake.now += timedelta(minutes=10)
    fake.controller.tick()
    prompt = Path(fake.spawns()[-1][fake.spawns()[-1].index("--prompt-file") + 1]).read_text()
    context = obj(json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0]))
    assert context["head_observed_at"] == datetime.fromtimestamp(observed, timezone.utc).isoformat()
    assert (
        context["review_not_before"]
        == datetime.fromtimestamp(observed + 600, timezone.utc).isoformat()
    )
    fake.record("waiting_review", pr="42", head_sha="abc")
    assert fake.job()["head_observed_at"] == observed


def test_postmerge_ci_and_docs_changes_are_in_watched_digest(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    fake.postmerge = "failure"
    first = fake.controller.digest(fake.controller.snapshot(fake.job()))
    fake.postmerge = "success"
    second = fake.controller.digest(fake.controller.snapshot(fake.job()))
    assert first != second


def test_failed_ci_does_not_restart_same_head_review_clock(fake: Fake) -> None:
    fake.waiting()
    observed = fake.job()["head_observed_at"]
    fake.now += timedelta(minutes=2)
    fake.ci = "failure"
    fake.controller.tick()
    assert fake.job()["head_observed_at"] == observed


def test_early_changed_head_followup_retains_one_due_review_recheck(fake: Fake) -> None:
    fake.waiting()
    fake.head = "new-head"
    fake.now += timedelta(minutes=10)
    fake.controller.tick()
    assert len(fake.spawns()) == 2
    assert fake.job()["review_pending"]
    observed = fake.job()["head_observed_at"]
    fake.record("waiting_review", head_sha="new-head")
    fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(minutes=11)
    fake.controller.tick()
    assert len(fake.spawns()) == 3
    assert not fake.job()["review_pending"]
    assert fake.job()["head_observed_at"] == observed
    fake.record("waiting_review", head_sha="new-head")
    fake.threads[-1]["status"] = "idle"
    fake.now += timedelta(minutes=11)
    fake.controller.tick()
    assert len(fake.spawns()) == 3


def _reopen_record(
    fake: Fake, *, status: str = "running", reason: str = "Owner requested resume"
) -> None:
    job = fake.job()
    fake.controller.record(
        parser().parse_args(
            [
                "--config",
                str(fake.config),
                "--state-dir",
                str(fake.state),
                "record",
                "--job",
                job["id"],
                "--thread-id",
                job["thread_id"],
                "--environment-id",
                job["environment_id"],
                "--workspace",
                job["workspace"],
                "--status",
                status,
                "--reason",
                reason,
                "--reopen",
            ]
        )
    )


@pytest.mark.parametrize("status", ["blocked", "inconclusive", "rejected"])
def test_owner_can_reopen_failed_job_without_losing_receipts(fake: Fake, status: str) -> None:
    fake.controller.tick()
    fake.record(status, reason="Earlier attempt did not qualify")
    previous = list(fake.job()["receipts"])
    _reopen_record(fake)
    assert fake.job()["status"] == "running"
    assert fake.job()["receipts"][:-1] == previous
    assert fake.job()["thread_id"] == fake.threads[0]["id"]


@pytest.mark.parametrize(
    ("job_status", "requested", "reason"),
    [
        ("complete", "running", "Owner request"),
        ("running", "running", "Owner request"),
        ("inconclusive", "complete", "Owner request"),
        ("inconclusive", "running", ""),
    ],
)
def test_reopen_requires_failed_job_running_status_and_reason(
    fake: Fake, job_status: str, requested: str, reason: str
) -> None:
    fake.controller.tick()
    job_id = fake.job()["id"]
    with fake.controller.store.locked():
        fake.controller.store.state["jobs"][job_id]["status"] = job_status
        fake.controller.store.save()
    with pytest.raises(DispatchError, match="Reopen requires"):
        _reopen_record(fake, status=requested, reason=reason)


@pytest.mark.parametrize("other_status", ["running", "waiting_ci", "waiting_review"])
def test_reopen_refuses_another_job_writer(fake: Fake, other_status: str) -> None:
    fake.controller.tick()
    fake.record("inconclusive", reason="Earlier attempt")
    with fake.controller.store.locked():
        other = fake.controller.new_job("daily:2026-10-28", "daily")
        other["status"] = other_status
        fake.controller.store.state["jobs"][other["id"]] = other
        fake.controller.store.save()
    with pytest.raises(DispatchError, match="Another job owns"):
        _reopen_record(fake)


def _non_runtime_evidence(fake: Fake) -> Path:
    path = fake.workspace / "example-validation.json"
    path.write_text(
        json.dumps(
            {
                "change_kind": "non_runtime",
                "head_sha": fake.head,
                "base_sha": "accepted-base",
                "example_validation": "passed",
                "measurement_review": "not_applicable",
            }
        )
    )
    return path


def _comparison_runner(fake: Fake, files: list[dict[str, str]]) -> None:
    def run(argv: list[str]) -> str:
        if "/compare/" in argv[-1]:
            return json.dumps({"files": files})
        return fake.run(argv)

    fake.controller.run = run


def test_non_runtime_completion_verifies_the_remote_diff(fake: Fake) -> None:
    fake.waiting()
    path = _non_runtime_evidence(fake)
    _comparison_runner(
        fake,
        [
            {"filename": "examples/ex_04_scopes_and_cleanup/05_unit_of_work.py"},
            {"filename": "docs/howto/patterns/unit-of-work.rst"},
            {"filename": "README.md"},
        ],
    )
    fake.controller.validate_non_runtime(
        fake.job(), {"accepted_base_sha": "accepted-base"}, str(path)
    )


@pytest.mark.parametrize(
    "field", ["change_kind", "head_sha", "base_sha", "example_validation", "measurement_review"]
)
def test_non_runtime_requires_exact_validated_example_evidence(fake: Fake, field: str) -> None:
    fake.waiting()
    path = _non_runtime_evidence(fake)
    evidence = json.loads(path.read_text())
    evidence[field] = "invalid"
    path.write_text(json.dumps(evidence))
    with pytest.raises(DispatchError, match="exact-head example validation"):
        fake.controller.validate_non_runtime(
            fake.job(), {"accepted_base_sha": "accepted-base"}, str(path)
        )


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"filename": "docs/guide.rst"}] * 300,
        [{"filename": "src/diwire/__init__.py"}],
        [{"filename": "uv.lock"}],
        [{"filename": "pyproject.toml"}],
        [{"filename": ".github/workflows/ci.yaml"}],
        [{"filename": "tools/unknown.py"}],
        [{"filename": "tools/bb_perf_dispatch.py"}],
        [{"filename": ".bb/automation/merge-gate.mjs"}],
        [{"filename": ".bb/workflows/daily-perf.js"}],
        [{"filename": "docs/guide.rst", "previous_filename": "src/diwire/__init__.py"}],
    ],
)
def test_non_runtime_rejects_incomplete_or_ineligible_diffs(
    fake: Fake, files: list[dict[str, str]]
) -> None:
    fake.waiting()
    path = _non_runtime_evidence(fake)
    _comparison_runner(fake, files)
    with pytest.raises(DispatchError, match="Non-runtime"):
        fake.controller.validate_non_runtime(
            fake.job(), {"accepted_base_sha": "accepted-base"}, str(path)
        )


def test_complete_accepts_verified_example_without_a_measurement_run(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    _comparison_runner(fake, [{"filename": "examples/transaction.py"}])
    fake.complete(non_runtime=True)
    assert fake.job()["status"] == "complete"


def test_example_completion_still_requires_matching_merged_tree(fake: Fake) -> None:
    fake.waiting()
    fake.merged = True
    _comparison_runner(fake, [{"filename": "src/diwire/__init__.py"}])
    with pytest.raises(DispatchError, match="ineligible path"):
        fake.complete(non_runtime=True)
    assert fake.job()["status"] != "complete"


def test_pre_pr_interruption_recovery_is_bounded_and_keeps_workflow_receipt(fake: Fake) -> None:
    fake.controller.tick()
    fake.record("running", receipt="workflow_run_id=wfr_saved")
    for attempt in range(2):
        fake.threads[-1]["status"] = "idle"
        fake.controller.tick()
        assert fake.job()["status"] == "running"
        assert fake.job()["recoveries"] == attempt + 1
        assert "--environment" in fake.spawns()[-1]
    fake.threads[-1]["status"] = "error"
    fake.controller.tick()
    assert fake.job()["status"] == "blocked"
    assert len(fake.spawns()) == 3
    assert any(
        receipt.get("receipts") == ["workflow_run_id=wfr_saved"]
        for receipt in fake.job()["receipts"]
    )


@pytest.mark.parametrize("pending_intent", [True, False])
def test_reopen_respects_provisioning_intents_and_live_terminal_roots(
    fake: Fake, *, pending_intent: bool
) -> None:
    fake.controller.tick()
    fake.record("inconclusive", reason="Earlier attempt")
    with fake.controller.store.locked():
        other = fake.controller.new_job("daily:2026-10-28", "daily")
        if pending_intent:
            other["intent"] = "DIWire daily:2026-10-28 / 0"
        else:
            other["status"] = "blocked"
            other["thread_id"] = "thr_other"
            fake.threads.append(
                {"id": "thr_other", "status": "active", "projectId": "proj_hypmgayr8j"}
            )
        fake.controller.store.state["jobs"][other["id"]] = other
        fake.controller.store.save()
    with pytest.raises(DispatchError, match="Another job owns"):
        _reopen_record(fake)


def _maintenance_evidence(
    fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[dict[str, str]], Path]:
    job = fake.job()
    storage = fake.state / job["thread_id"]
    storage.mkdir()
    pinned = fake.state / "dispatcher.py"
    pinned.write_text("# Independently reviewed pinned dispatcher")
    monkeypatch.setattr("tools.bb_perf_dispatch.__file__", str(pinned))
    monkeypatch.setenv("BB_THREAD_STORAGE", str(storage))
    monkeypatch.setenv("BB_THREAD_ID", job["thread_id"])
    files = [
        {"filename": ".bb/automation/merge-gate.mjs"},
        {"filename": "tools/bb_perf_dispatch.py"},
    ]
    paths = sorted(file["filename"] for file in files)
    authorization = storage / "authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "kind": "owner_authorized_automation_maintenance",
                "root_thread_id": job["thread_id"],
                "owner_request": "Owner explicitly requested this automation update",
                "head_sha": fake.head,
                "base_sha": "accepted-base",
                "changed_paths_sha256": hashlib.sha256(
                    json.dumps(paths, separators=(",", ":")).encode()
                ).hexdigest(),
                "dispatcher_sha256": hashlib.sha256(pinned.read_bytes()).hexdigest(),
            }
        )
    )
    evidence = _non_runtime_evidence(fake)
    value = json.loads(evidence.read_text())
    value.update(change_kind="automation_maintenance", owner_authorization_path=str(authorization))
    evidence.write_text(json.dumps(value))
    _comparison_runner(fake, files)
    return evidence, files, authorization


def test_explicit_owner_maintenance_uses_pinned_exact_update_evidence(
    fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.waiting()
    evidence, _, _ = _maintenance_evidence(fake, monkeypatch)
    fake.controller.validate_non_runtime(
        fake.job(),
        {"accepted_base_sha": "accepted-base", "change_kind": "automation_maintenance"},
        str(evidence),
    )


@pytest.mark.parametrize(
    "field",
    [
        "kind",
        "root_thread_id",
        "owner_request",
        "head_sha",
        "base_sha",
        "changed_paths_sha256",
        "dispatcher_sha256",
    ],
)
def test_owner_maintenance_rejects_changed_authorization(
    fake: Fake, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    fake.waiting()
    evidence, _, authorization = _maintenance_evidence(fake, monkeypatch)
    value = json.loads(authorization.read_text())
    value[field] = ""
    authorization.write_text(json.dumps(value))
    with pytest.raises(DispatchError, match="authorization does not match"):
        fake.controller.validate_non_runtime(
            fake.job(),
            {"accepted_base_sha": "accepted-base", "change_kind": "automation_maintenance"},
            str(evidence),
        )


@pytest.mark.parametrize("candidate_controlled", [True, False])
def test_owner_maintenance_requires_root_storage_and_outside_checkout_dispatcher(
    fake: Fake, monkeypatch: pytest.MonkeyPatch, *, candidate_controlled: bool
) -> None:
    fake.waiting()
    evidence, files, _authorization = _maintenance_evidence(fake, monkeypatch)
    value = json.loads(evidence.read_text())
    if candidate_controlled:
        monkeypatch.setattr(
            "tools.bb_perf_dispatch.__file__", str(fake.workspace / "tools" / "bb_perf_dispatch.py")
        )
    else:
        value["owner_authorization_path"] = str(fake.workspace / "authorization.json")
    with pytest.raises(DispatchError, match="root-owned authorization and a pinned dispatcher"):
        fake.controller.validate_owner_maintenance(fake.job(), value, files)


@pytest.mark.parametrize("missing", [True, False])
def test_owner_maintenance_rejects_missing_or_wrong_root_storage(
    fake: Fake, monkeypatch: pytest.MonkeyPatch, *, missing: bool
) -> None:
    fake.waiting()
    evidence, files, _ = _maintenance_evidence(fake, monkeypatch)
    if missing:
        monkeypatch.delenv("BB_THREAD_STORAGE")
    else:
        monkeypatch.setenv("BB_THREAD_STORAGE", str(fake.state))
    with pytest.raises(DispatchError, match="root-owned authorization"):
        fake.controller.validate_owner_maintenance(
            fake.job(), json.loads(evidence.read_text()), files
        )
