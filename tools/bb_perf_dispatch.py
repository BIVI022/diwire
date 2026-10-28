"""Dispatch DIWire jobs without installing Python dependencies.

Run: python3 /absolute/tools/bb_perf_dispatch.py --config CONFIG --state-dir STATE
{tick [--dry-run] [--now ISO_TIMESTAMP],status,record --help,patch-version v1.2.3}.
Use one BB script automation every ten minutes. No command targets an old chat. --now is allowed only with --dry-run.

Config JSON keys: project_id, repository (owner/name), checkout, prompt_directory,
provider, model, reasoning. Optional schedule keys: timezone="Europe/Minsk",
daily_time="09:00", release_day="Monday", release_time="12:00",
review_wait_seconds=600, review_deadline_seconds=86400, max_recovery_attempts=2.
Paths must be absolute. DAILY.md, FOLLOWUP.md and RELEASE.md must exist.
The appended JSON job context has these keys: job_id, kind, date, state_dir,
config_path, dispatcher_path, thread_id, environment_id, workspace, pr, head_sha,
reason, record_command, authorized_commands, snapshot_path, head_observed_at,
review_not_before. The last two are UTC ISO timestamps (null before a PR head is
known). The review clock persists across followups for the same head. New roots read their
actual identity from BB_THREAD_ID and `bb thread show`. Hidden workers must not
record. record_command is a shell-quoted prefix; append required record flags.

State schema 1 contains jobs keyed by daily:YYYY-MM-DD or release:YYYY-Www.
Receipts retain decisions and evidence. Weekly release queues survive midnight.
An expired queued daily slot becomes inconclusive with its busy reason. Intent titles are immutable identifiers.
Unknown spawn outcomes remain claimed until list/show reconciliation succeeds.
A missing result is retried on a later tick, with a bounded recovery count.
The digest tracks the last dispatched snapshot, not unread observations. Each
first wait gets one followup after ten minutes; unchanged inspected state does
not wake another agent. Complete daily jobs need both main CI and Docs at the
exact merge SHA. An external merge always needs a new reconciliation root,
never automatic completion. Daily complete requires --receipt accepted_head_sha,
accepted_base_sha, accepted_tree_sha and merge_sha. Both accepted head tree and
actual merge tree must match; the first merge parent must equal accepted base.
The validation evidence path must name a nonempty absolute file.
Release complete requires validation evidence and --receipt keys previous_version,
release_version, release_url, publish_run_id, wheel_sha256 and sdist_sha256.
Release waiting_ci without a PR requires --receipt publish_run_id=NUMBER.
No useful release: use inconclusive with reason and --receipt no_release=true.
Only agents merge or publish. The controller reads BB/GitHub and fetches main.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, NoReturn, TypedDict, cast
from zoneinfo import ZoneInfo

TERMINAL: Final = frozenset({"complete", "rejected", "inconclusive", "blocked"})
WAITING: Final = frozenset({"waiting_review", "waiting_ci"})
STATUSES: Final = TERMINAL | WAITING | {"running"}
LIVE: Final = frozenset({"pending", "starting", "active", "stopping"})
DONE: Final = frozenset({"idle", "error"})
SCHEMA: Final = 1
MIN_REVIEW_WAIT: Final = 600
MAX_RECOVERIES: Final = 2
COMPARE_FILE_LIMIT: Final = 300
POSTMERGE_WORKFLOWS: Final = frozenset({".github/workflows/ci.yaml", ".github/workflows/docs.yaml"})
Runner = Callable[[list[str]], str]
Clock = Callable[[], datetime]
Fetcher = Callable[[str], object]


class DispatchError(RuntimeError):
    """Reject an unsafe controller operation or invalid runtime data."""


def fail(message: str) -> NoReturn:
    raise DispatchError(message)


def obj(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        fail("Expected a JSON object")
    return cast("dict[str, object]", value)


def rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        fail("Expected a JSON array")
    return [obj(item) for item in cast("list[object]", value)]


def run_command(argv: list[str]) -> str:
    """Run a bounded command without a shell."""
    return subprocess.run(  # noqa: S603 - argv is explicit; no shell is used.
        argv, check=True, capture_output=True, text=True, timeout=55
    ).stdout


def fetch_json(url: str) -> object:
    """Read public PyPI metadata with a bounded stdlib HTTP request."""
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - fixed HTTPS PyPI URL.
        value: object = json.load(response)
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def patch_version(version: str) -> str:
    """Increment only the last number in a strict vX.Y.Z version."""
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
    if match is None:
        fail("Expected a version in vX.Y.Z form")
    major, minor, patch = match.groups()
    return f"v{major}.{minor}.{int(patch) + 1}"


@dataclass(frozen=True)
class Config:
    """Validated controller configuration."""

    project_id: str
    repository: str
    checkout: str
    prompt_directory: str
    provider: str
    model: str
    reasoning: str
    timezone: str = "Europe/Minsk"
    daily_time: str = "09:00"
    release_day: str = "Monday"
    release_time: str = "12:00"
    review_wait_seconds: int = 600
    review_deadline_seconds: int = 86400
    max_recovery_attempts: int = 2

    @classmethod
    def load(cls, path: Path) -> Config:
        """Read config without silently accepting misspelled fields."""
        data = obj(json.loads(path.read_text()))
        names = cls.__dataclass_fields__
        if data.keys() - names.keys():
            fail("Unknown configuration keys")
        strings = [
            "project_id",
            "repository",
            "checkout",
            "prompt_directory",
            "provider",
            "model",
            "reasoning",
        ]
        values = {key: str(data.get(key, "")) for key in strings}
        if any(not isinstance(data.get(key), str) or not values[key] for key in strings):
            fail("Missing required string configuration key")
        config = cls(
            values["project_id"],
            values["repository"],
            values["checkout"],
            values["prompt_directory"],
            values["provider"],
            values["model"],
            values["reasoning"],
        )
        optional = asdict(config)
        optional.update(data)
        # JSON boundary: types are checked before constructing the dataclass.
        for key, value in optional.items():
            expected = int if key.endswith("seconds") or key == "max_recovery_attempts" else str
            if type(value) is not expected:
                fail(f"Invalid configuration type: {key}")
        config = cls(
            project_id=cast("str", optional["project_id"]),
            repository=cast("str", optional["repository"]),
            checkout=cast("str", optional["checkout"]),
            prompt_directory=cast("str", optional["prompt_directory"]),
            provider=cast("str", optional["provider"]),
            model=cast("str", optional["model"]),
            reasoning=cast("str", optional["reasoning"]),
            timezone=cast("str", optional["timezone"]),
            daily_time=cast("str", optional["daily_time"]),
            release_day=cast("str", optional["release_day"]),
            release_time=cast("str", optional["release_time"]),
            review_wait_seconds=cast("int", optional["review_wait_seconds"]),
            review_deadline_seconds=cast("int", optional["review_deadline_seconds"]),
            max_recovery_attempts=cast("int", optional["max_recovery_attempts"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Fail before dispatch if config or prompts are unavailable."""
        if self.project_id != "proj_hypmgayr8j":
            fail("project_id must be proj_hypmgayr8j")
        if re.fullmatch(r"[\w.-]+/[\w.-]+", self.repository) is None:
            fail("repository must be owner/name")
        if self.timezone != "Europe/Minsk" or self.release_day != "Monday":
            fail("Use Europe/Minsk and Monday PATCH releases")
        self.validate_schedule()
        for value in (self.checkout, self.prompt_directory):
            if not Path(value).is_absolute() or not Path(value).is_dir():
                fail(f"Missing absolute directory: {value}")
        for name in ("DAILY.md", "FOLLOWUP.md", "RELEASE.md"):
            if not (Path(self.prompt_directory) / name).is_file():
                fail(f"Missing prompt file: {name}")

    def validate_schedule(self) -> None:
        """Validate local times and recovery limits."""
        ZoneInfo(self.timezone)
        for value in (self.daily_time, self.release_time):
            if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
                fail("Schedule time must use HH:MM")
        if not MIN_REVIEW_WAIT <= self.review_wait_seconds <= self.review_deadline_seconds:
            fail("Review wait must be at least 600 seconds and no greater than deadline")
        if not 0 <= self.max_recovery_attempts <= MAX_RECOVERIES:
            fail("Recovery attempts must be between zero and two")


class Job(TypedDict):
    """Persisted job claim and agent receipts."""

    id: str
    kind: str
    date: str
    status: str
    thread_id: str
    environment_id: str
    workspace: str
    pr: int
    head_sha: str
    created: float
    wait_since: float
    head_observed_at: float
    review_pending: bool
    digest: str
    recoveries: int
    generation: int
    intent: str
    reason: str
    receipts: list[dict[str, object]]


class State(TypedDict):
    """Versioned file protected by the controller lock."""

    schema: int
    jobs: dict[str, Job]


class Store:
    """Serialize ticks and records with atomic, durable writes."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.state: State = {"schema": SCHEMA, "jobs": {}}

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold a process lock for the full read/modify/write transaction."""
        with (self.path / "lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            target = self.path / "state.json"
            if target.exists():
                data = obj(json.loads(target.read_text()))
                if data.get("schema") != SCHEMA:
                    fail("Unsupported state schema")
                jobs = obj(data.get("jobs"))
                for key, raw in jobs.items():
                    job = obj(raw)
                    if job.get("id") != key or job.get("status") not in STATUSES | {"queued"}:
                        fail("Invalid persisted job")
                self.state = cast("State", data)
            yield

    def write_json(self, path: Path, value: object) -> None:
        """Replace a JSON file only after flushing its complete contents."""
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(value, handle, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                temporary.replace(path)
                directory = os.open(self.path, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)

    def save(self) -> None:
        """Persist a job claim before the next external side effect."""
        self.write_json(self.path / "state.json", self.state)


class Controller:
    """Run short deterministic ticks; agents own all repository writes."""

    def __init__(
        self,
        config_path: Path,
        state_dir: Path,
        *,
        runner: Runner = run_command,
        clock: Clock = utc_now,
        fetcher: Fetcher = fetch_json,
    ) -> None:
        self.config_path = config_path.resolve()
        self.config = Config.load(self.config_path)
        self.store = Store(state_dir)
        self.run = runner
        self.clock = clock
        self.fetch = fetcher

    def json(self, argv: list[str]) -> object:
        """Parse a checked command result at the JSON boundary."""
        value: object = json.loads(self.run(argv))
        if isinstance(value, dict) and value.get("ok") is False:
            fail(f"Tool error: {value}")
        return value

    def threads(self) -> list[dict[str, object]]:
        """Read actual BB list shape; include archived and hidden claims."""
        base = [
            "bb",
            "thread",
            "list",
            "--project",
            self.config.project_id,
            "--include-hidden",
            "--json",
        ]
        return rows(self.json(base)) + rows(self.json([*base, "--archived"]))

    def show(self, thread_id: str) -> dict[str, object]:
        """Read the wrapped thread/environment shape from BB."""
        return obj(self.json(["bb", "thread", "show", thread_id, "--json"]))

    def receipt(self, job: Job, reason: str, **evidence: object) -> None:
        """Keep the reason and evidence for each controller decision."""
        job["reason"] = reason
        job["receipts"].append({"at": self.clock().isoformat(), "reason": reason, **evidence})

    def accept_thread(self, job: Job, thread: dict[str, object]) -> bool:
        """Resolve an intent even if its environment is still provisioning."""
        thread_id = str(thread["id"])
        details = self.show(thread_id)
        actual = obj(details["thread"])
        if (
            actual.get("projectId") != self.config.project_id
            or actual.get("title") != job["intent"]
        ):
            fail("Thread identity does not match dispatch intent")
        job["thread_id"] = thread_id
        environment = details.get("environment")
        if environment is None and actual.get("status") in DONE:
            job["intent"] = ""
            job["status"] = "blocked"
            self.receipt(
                job,
                "Worker ended before environment provisioning",
                thread_id=thread_id,
                thread_status=actual["status"],
            )
            self.store.save()
            return False
        if environment is None:
            self.receipt(job, "Environment is still provisioning", thread_id=thread_id)
            self.store.save()
            return False
        env = obj(environment)
        if job["environment_id"] and env.get("id") != job["environment_id"]:
            fail("Followup environment does not match saved job")
        job["environment_id"] = str(env["id"])
        job["workspace"] = str(env["path"])
        job["intent"] = ""
        job["status"] = "running"
        self.receipt(job, "Dispatch confirmed", thread_id=thread_id, environment_id=env["id"])
        self.store.save()
        return True

    def reconcile(self, job: Job) -> bool:
        """Find an exact immutable title before any retry of an unknown spawn."""
        found = {str(row["id"]): row for row in self.threads() if row.get("title") == job["intent"]}
        if len(found) > 1:
            fail(f"Multiple threads match intent {job['intent']}")
        if found:
            self.accept_thread(job, next(iter(found.values())))
            return True
        return False

    def prompt(self, job: Job) -> Path:
        """Append explicit job context to the parent-owned prompt."""
        name = "FOLLOWUP.md" if job["generation"] else f"{job['kind'].upper()}.md"
        source = Path(self.config.prompt_directory) / name
        dispatcher = str(Path(__file__).resolve())
        prefix = [
            "python3",
            dispatcher,
            "--config",
            str(self.config_path),
            "--state-dir",
            str(self.store.path),
            "record",
            "--job",
            job["id"],
        ]
        context: dict[str, object] = {
            key: job[key]
            for key in (
                "kind",
                "date",
                "thread_id",
                "environment_id",
                "workspace",
                "pr",
                "head_sha",
                "reason",
            )
        }
        context["thread_id"] = None
        observed = job["head_observed_at"]
        context["head_observed_at"] = (
            datetime.fromtimestamp(observed, timezone.utc).isoformat() if observed else None
        )
        context["review_not_before"] = (
            datetime.fromtimestamp(
                observed + self.config.review_wait_seconds, timezone.utc
            ).isoformat()
            if observed
            else None
        )
        context.update(
            job_id=job["id"],
            state_dir=str(self.store.path),
            config_path=str(self.config_path),
            dispatcher_path=dispatcher,
            merge_gate_path=str(Path(dispatcher).parent / "merge-gate.mjs"),
            record_command=shlex.join(prefix),
            snapshot_path=str(self.store.path / f"{job['id']}.snapshot.json"),
            authorized_commands=[
                "findings",
                "implementation",
                "Linux measurement CI",
                "PR",
                "AI review",
                "fix",
                "validation",
                "E2E",
                "exact-head merge",
                "postmerge CI",
            ]
            + (["Monday PATCH release"] if job["kind"] == "release" else []),
        )
        path = self.store.path / f"{job['id']}.{job['generation']}.prompt.md"
        path.write_text(
            source.read_text()
            + "\n\nJob context (root owner only):\n```json\n"
            + json.dumps(context, indent=2)
            + "\n```\n"
        )
        return path

    def spawn(self, job: Job) -> None:
        """Persist intent before calling BB. Never use a target-thread flag."""
        if not job["intent"]:
            job["intent"] = f"DIWire {job['id']} / {job['generation']}"
            self.store.save()
        path = self.prompt(job)
        cfg = self.config
        argv = [
            "bb",
            "thread",
            "spawn",
            "--project",
            cfg.project_id,
            "--provider",
            cfg.provider,
            "--model",
            cfg.model,
            "--reasoning-level",
            cfg.reasoning,
            "--permission-mode",
            "full",
            "--visibility",
            "visible",
            "--title",
            job["intent"],
            "--prompt-file",
            str(path),
            "--json",
        ]
        if job["generation"]:
            if not job["environment_id"]:
                fail("Cannot open a followup without a provisioned job environment")
            argv.extend(["--environment", job["environment_id"]])
        else:
            self.run(["git", "-C", cfg.checkout, "fetch", "origin", "main"])
            argv.extend(["--new-environment", "worktree", "--base-branch", "origin/main"])
        # An exception deliberately leaves the durable intent for next-tick reconciliation.
        thread = obj(self.json(argv))
        self.accept_thread(job, thread)

    def retry_intent(self, job: Job) -> None:
        """Retry only after reconciliation and with a fixed recovery budget."""
        if self.reconcile(job):
            return
        if job["recoveries"] >= self.config.max_recovery_attempts:
            job["status"] = "blocked"
            self.receipt(
                job,
                "No thread found after bounded reconciliation; dispatch abandoned",
                intent=job["intent"],
                matches=[],
            )
            job["intent"] = ""
            self.store.save()
            return
        job["recoveries"] += 1
        self.receipt(job, "No thread matched dispatch intent; bounded retry")
        self.store.save()
        self.spawn(job)

    def busy(self, job: Job) -> bool:
        """Exclude other writers while a worker or PR is active."""
        if job["intent"]:
            return True
        if job["status"] == "queued":
            return False
        if job["thread_id"] and self.worker_live(job):
            return True
        if job["status"] in TERMINAL:
            return False
        if job["status"] == "running" and job["pr"]:
            job["status"] = "waiting_ci"
            job["wait_since"] = self.clock().timestamp()
            self.receipt(job, "Worker ended with an open PR; retain CI watch")
            self.store.save()
        elif job["status"] == "running":
            self.recover_interrupted(job)
        return job["status"] in WAITING or job["status"] == "running"

    def recover_interrupted(self, job: Job) -> None:
        """Resume a pre-PR interruption in the same worktree, within the budget."""
        if not job["environment_id"] or job["recoveries"] >= self.config.max_recovery_attempts:
            job["status"] = "blocked"
            self.receipt(job, "Pre-PR interruption cannot recover; inspect saved workflow evidence")
            self.store.save()
            return
        job["recoveries"] += 1
        self.wake(
            job, "Pre-PR owner interrupted; resume saved workflow or example in same worktree"
        )

    def pages(self, endpoint: str) -> list[object]:
        """Read all REST pages, without dropping review bodies or comments."""
        value = self.json(["gh", "api", "--paginate", "--slurp", endpoint])
        if not isinstance(value, list):
            fail("Expected paginated gh API response")
        return cast("list[object]", value)

    def snapshot(self, job: Job) -> dict[str, object]:
        """Collect full PR conversations, review threads, checks and contexts."""
        if job["kind"] == "release" and not job["pr"]:
            return self.release_snapshot(job)
        repo = self.config.repository
        root = f"repos/{repo}"
        pr = obj(self.json(["gh", "api", f"{root}/pulls/{job['pr']}"]))
        head = str(obj(pr["head"])["sha"])
        snapshot: dict[str, object] = {"pr": pr}
        for name, path in {
            "reviews": f"pulls/{job['pr']}/reviews",
            "comments": f"issues/{job['pr']}/comments",
            "review_comments": f"pulls/{job['pr']}/comments",
            "checks": f"commits/{head}/check-runs",
            "statuses": f"commits/{head}/statuses",
        }.items():
            snapshot[name] = self.pages(f"{root}/{path}?per_page=100")
        owner, name = repo.split("/")
        query = "query($owner:String!,$name:String!,$number:Int!,$endCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$endCursor){nodes{id isResolved isOutdated comments(first:100){nodes{id body updatedAt author{login}} pageInfo{hasNextPage endCursor}}} pageInfo{hasNextPage endCursor}}}}}"
        pages = self.json(
            [
                "gh",
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={job['pr']}",
            ]
        )
        threads: list[dict[str, object]] = []
        for page in rows(pages):
            if page.get("errors"):
                fail("GraphQL review thread query failed")
            connection = obj(
                obj(obj(obj(page["data"])["repository"])["pullRequest"])["reviewThreads"]
            )
            for thread in rows(connection["nodes"]):
                comments = obj(thread["comments"])
                if obj(comments["pageInfo"])["hasNextPage"]:
                    query_comments = "query($id:ID!,$endCursor:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$endCursor){nodes{id body updatedAt author{login}} pageInfo{hasNextPage endCursor}}}}}"
                    thread["all_comments"] = self.json(
                        [
                            "gh",
                            "api",
                            "graphql",
                            "--paginate",
                            "--slurp",
                            "-f",
                            f"query={query_comments}",
                            "-f",
                            f"id={thread['id']}",
                        ]
                    )
                if "all_comments" in thread and any(
                    page.get("errors") for page in rows(thread["all_comments"])
                ):
                    fail("GraphQL review comments query failed")
                threads.append(thread)
        snapshot["threads"] = threads
        if pr.get("merged"):
            snapshot["postmerge_runs"] = self.pages(
                f"{root}/actions/runs?head_sha={pr['merge_commit_sha']}&event=push&branch=main&per_page=100"
            )
        self.store.write_json(self.store.path / f"{job['id']}.snapshot.json", snapshot)
        return snapshot

    @staticmethod
    def extra_receipts(job: Job) -> dict[str, str]:
        """Read additional typed key=value receipts in chronological order."""
        result: dict[str, str] = {}
        for receipt in job["receipts"]:
            values = receipt.get("receipts", [])
            if not isinstance(values, list):
                fail("Invalid extra receipts")
            for value in values:
                key, separator, content = str(value).partition("=")
                if not separator or not key:
                    fail("Extra receipts must use key=value")
                result[key] = content
        return result

    def release_snapshot(self, job: Job) -> dict[str, object]:
        """Watch publication CI for a release that has no new PR."""
        receipts = self.extra_receipts(job)
        run_id = receipts.get("publish_run_id", "")
        if not run_id.isdecimal():
            fail("Release waiting_ci without PR requires publish_run_id receipt")
        snapshot = {
            "publish_run": self.json(
                ["gh", "api", f"repos/{self.config.repository}/actions/runs/{run_id}"]
            )
        }
        self.store.write_json(self.store.path / f"{job['id']}.snapshot.json", snapshot)
        return snapshot

    @staticmethod
    def digest(snapshot: dict[str, object]) -> str:
        """Hash actionable PR fields and complete review/check evidence."""
        if "pr" not in snapshot:
            return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        meaningful = dict(snapshot)
        pr = obj(snapshot["pr"])
        meaningful["pr"] = {
            key: pr.get(key)
            for key in (
                "head",
                "state",
                "merged",
                "merge_commit_sha",
                "mergeable",
                "mergeable_state",
                "draft",
            )
        }
        obj(meaningful["pr"])["head"] = obj(pr["head"])["sha"]
        return hashlib.sha256(json.dumps(meaningful, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def has_evidence(job: Job) -> bool:
        """Require saved validation and measured Linux CI receipts."""
        return any(
            receipt.get("validation_evidence")
            and receipt.get("measurement_run_url")
            and receipt.get("head_sha") == job["head_sha"]
            for receipt in job["receipts"]
        )

    def postmerge_ok(self, pr: dict[str, object]) -> bool:
        """Require completed push CI on the actual merge commit."""
        sha = pr.get("merge_commit_sha")
        if not pr.get("merged") or not sha:
            return False
        pages = self.pages(
            f"repos/{self.config.repository}/actions/runs?head_sha={sha}&event=push&branch=main&per_page=100"
        )
        runs = [run for page in pages for run in rows(obj(page)["workflow_runs"])]
        latest: dict[str, dict[str, object]] = {}
        for run in runs:
            path = str(run.get("path"))
            if path not in POSTMERGE_WORKFLOWS:
                continue
            previous = latest.get(path)
            if previous is None or self.run_rank(run) > self.run_rank(previous):
                latest[path] = run
        return latest.keys() == POSTMERGE_WORKFLOWS and all(
            run.get("head_sha") == sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            for run in latest.values()
        )

    @staticmethod
    def run_rank(run: dict[str, object]) -> tuple[int, ...]:
        """Order retries and new runs without relying on API page ordering."""
        return tuple(int(str(run.get(key, 0))) for key in ("run_number", "run_attempt", "id"))

    def wake(self, job: Job, reason: str) -> None:
        """Claim a new visible root in the existing environment."""
        if (
            job["head_observed_at"]
            and self.clock().timestamp()
            >= job["head_observed_at"] + self.config.review_wait_seconds
        ):
            job["review_pending"] = False
        job["generation"] += 1
        job["status"] = "running"
        self.receipt(job, reason)
        self.spawn(job)

    def deadline(self, job: Job) -> None:
        """Bound recovery attempts and retain an honest terminal outcome."""
        if job["recoveries"] < self.config.max_recovery_attempts:
            job["recoveries"] += 1
            job["wait_since"] = self.clock().timestamp()
            self.wake(job, "Review/CI deadline recovery")
        else:
            job["status"] = "blocked"
            self.receipt(job, "Review/CI deadline exhausted recovery budget")
            self.store.save()

    def watch_release(self, job: Job) -> None:
        """Wake a release owner only for publication changes or its deadline."""
        snapshot = self.release_snapshot(job)
        digest = self.digest(snapshot)
        age = self.clock().timestamp() - job["wait_since"]
        failed = obj(snapshot["publish_run"]).get("conclusion") in {
            "failure",
            "cancelled",
            "timed_out",
        }
        if age >= self.config.review_deadline_seconds:
            self.deadline(job)
        elif digest != job["digest"] and (failed or age >= self.config.review_wait_seconds):
            job["digest"] = digest
            self.wake(job, "Publication CI changed")

    def watch(self, job: Job) -> None:
        """Wake only for changed evidence or a bounded deadline recovery."""
        if job["kind"] == "release" and not job["pr"]:
            self.watch_release(job)
            return
        snapshot = self.snapshot(job)
        pr = obj(snapshot["pr"])
        head = str(obj(pr["head"])["sha"])
        digest = self.digest(snapshot)
        changed_head = head != job["head_sha"]
        checks = [
            check
            for page in cast("list[object]", snapshot["checks"])
            for check in rows(obj(page)["check_runs"])
        ]
        all_statuses = [
            status for page in cast("list[object]", snapshot["statuses"]) for status in rows(page)
        ]
        latest_statuses: dict[str, dict[str, object]] = {}
        for status in all_statuses:
            latest_statuses.setdefault(str(status.get("context")), status)
        statuses = list(latest_statuses.values())
        failing = any(
            check.get("conclusion")
            in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
            for check in checks
        ) or any(status.get("state") in {"failure", "error"} for status in statuses)
        age = self.clock().timestamp() - job["wait_since"]
        review_age = self.clock().timestamp() - job["head_observed_at"]
        previous_digest = job["digest"]
        if changed_head or (failing and digest != previous_digest):
            job["head_sha"] = head
            if changed_head:
                job["head_observed_at"] = self.clock().timestamp()
                job["review_pending"] = True
            job["digest"] = digest
            job["wait_since"] = self.clock().timestamp()
            self.wake(
                job, "Head changed; invalidate prior validation" if changed_head else "CI failed"
            )
        elif age >= self.config.review_deadline_seconds:
            self.deadline(job)
        elif review_age >= self.config.review_wait_seconds and (
            job["review_pending"] or digest != job["digest"]
        ):
            job["digest"] = digest
            self.wake(
                job,
                "Merged PR requires validation reconciliation"
                if pr.get("merged")
                else "PR evidence changed",
            )

    def due(self) -> list[tuple[str, str]]:
        """Use local calendar keys; never backfill an unbounded history."""
        now = self.clock().astimezone(ZoneInfo(self.config.timezone))
        jobs = []
        if now.strftime("%H:%M") >= self.config.daily_time:
            jobs.append((f"daily:{now.date()}", "daily"))
        if (
            now.strftime("%A") == self.config.release_day
            and now.strftime("%H:%M") >= self.config.release_time
        ):
            jobs.append((f"release:{now.strftime('%G-W%V')}", "release"))
        return jobs

    def new_job(self, key: str, kind: str) -> Job:
        """Create a queued, auditable calendar slot."""
        return Job(
            id=key,
            kind=kind,
            date=self.clock().astimezone(ZoneInfo(self.config.timezone)).date().isoformat(),
            status="queued",
            thread_id="",
            environment_id="",
            workspace="",
            pr=0,
            head_sha="",
            created=self.clock().timestamp(),
            wait_since=0,
            head_observed_at=0,
            review_pending=False,
            digest="",
            recoveries=0,
            generation=0,
            intent="",
            reason="",
            receipts=[],
        )

    def tick(self, *, dry_run: bool = False) -> dict[str, object]:
        """Run one controller transaction without sleeping or agent polling."""
        with self.store.locked():
            if dry_run:
                return {"wakeAgent": False, "due": self.due(), "jobs": self.store.state["jobs"]}
            jobs = self.store.state["jobs"]
            for job in list(jobs.values()):
                if job["intent"]:
                    self.retry_intent(job)
                elif job["status"] in WAITING and not self.worker_live(job):
                    self.watch(job)
            busy = any(self.busy(job) for job in jobs.values())
            for key, kind in self.due():
                if key not in jobs:
                    jobs[key] = self.new_job(key, kind)
            self.drain_queue(busy=busy)
            self.store.save()
        return {"wakeAgent": False}

    def drain_queue(self, *, busy: bool) -> None:
        """Retain weekly release slots across midnight without daily backlogs."""
        today = self.clock().astimezone(ZoneInfo(self.config.timezone)).date().isoformat()
        for job in self.store.state["jobs"].values():
            if job["status"] != "queued":
                continue
            if job["kind"] == "daily" and job["date"] != today:
                job["status"] = "inconclusive"
                self.receipt(job, "Daily date passed while another job owned the writer")
            elif busy:
                if job["reason"] != "Queued: another job owns the writer":
                    self.receipt(job, "Queued: another job owns the writer")
            else:
                self.spawn(job)
                busy = True

    def worker_live(self, job: Job) -> bool:
        """Inspect the current owner once; never use a timed lease as proof."""
        if not job["thread_id"]:
            fail("Job has no owner thread")
        thread = obj(self.show(job["thread_id"])["thread"])
        status = thread.get("status")
        if status not in LIVE | DONE:
            fail("Unknown BB worker status")
        if (
            status in LIVE
            or thread.get("activeBackgroundAgentCount")
            or thread.get("queuedMessageCount")
        ):
            return True
        # BB can leave a root idle while its saved workflow or child process runs.
        listed = next((row for row in self.threads() if row["id"] == job["thread_id"]), None)
        return listed is not None and any(obj(listed.get("activity", {})).values())

    def record(self, args: argparse.Namespace) -> None:
        """Accept receipts only from the current root and saved environment."""
        with self.store.locked():
            job = self.store.state["jobs"].get(args.job)
            if job is None:
                fail("Unknown job")
            if job["intent"] and not self.reconcile(job):
                fail("Owner dispatch is not yet confirmed")
            if (args.thread_id, args.environment_id, str(Path(args.workspace).resolve())) != (
                job["thread_id"],
                job["environment_id"],
                job["workspace"],
            ):
                fail("Stale thread or environment receipt")
            if args.reopen:
                self.validate_reopen(job, args)
            elif job["status"] in TERMINAL:
                fail("Terminal job cannot change")
            if args.status in TERMINAL and not args.reason:
                fail("Terminal status requires a reason")
            previous_head = job["head_sha"]
            self.validate_record(job, args)
            if job["head_sha"] and (
                not job["head_observed_at"] or previous_head != job["head_sha"]
            ):
                job["head_observed_at"] = self.clock().timestamp()
                job["review_pending"] = True
            self.receipt(
                job,
                args.reason or args.status,
                head_sha=job["head_sha"],
                validation_evidence=args.validation_evidence,
                measurement_run_url=args.measurement_run_url,
                receipts=args.receipt,
            )
            if args.status in WAITING and (
                job["status"] not in WAITING or job["head_sha"] != previous_head
            ):
                job["wait_since"] = self.clock().timestamp()
            job["status"] = args.status
            self.store.save()

    def validate_reopen(self, job: Job, args: argparse.Namespace) -> None:
        """Keep owner-requested recovery separate from ordinary receipts."""
        if (
            job["status"] not in {"blocked", "rejected", "inconclusive"}
            or args.status != "running"
            or not args.reason
        ):
            fail("Reopen requires a failed job, running status and an owner reason")
        if any(
            other["id"] != job["id"]
            and (
                other["intent"]
                or other["status"] in {"running", "waiting_review", "waiting_ci"}
                or (other["thread_id"] and self.worker_live(other))
            )
            for other in self.store.state["jobs"].values()
        ):
            fail("Another job owns the writer")

    def release_complete(self, args: argparse.Namespace) -> None:
        """Verify PATCH publication, exact publish run and PyPI file hashes."""
        self.evidence_file(args.validation_evidence)
        receipts = dict(item.split("=", 1) for item in args.receipt)
        required = {
            "previous_version",
            "release_version",
            "release_url",
            "publish_run_id",
            "wheel_sha256",
            "sdist_sha256",
        }
        if required - receipts.keys() or not args.validation_evidence:
            fail("Release complete requires publication receipts and validation evidence")
        version = receipts["release_version"]
        if patch_version(receipts["previous_version"]) != version:
            fail("Release must increment PATCH only")
        root = f"repos/{self.config.repository}"
        release = obj(self.json(["gh", "api", f"{root}/releases/tags/{version}"]))
        if (
            release.get("draft")
            or release.get("prerelease")
            or release.get("html_url") != receipts["release_url"]
        ):
            fail("Published GitHub release does not match receipt")
        publish = obj(
            self.json(["gh", "api", f"{root}/actions/runs/{int(receipts['publish_run_id'])}"])
        )
        if (
            publish.get("status") != "completed"
            or publish.get("conclusion") != "success"
            or publish.get("head_branch") != version
            or publish.get("event") != "release"
            or publish.get("path") != ".github/workflows/publish.yaml"
        ):
            fail("Exact release publish run has not succeeded")
        tag = obj(self.json(["gh", "api", f"{root}/commits/{version}"]))
        if publish.get("head_sha") != tag.get("sha"):
            fail("Publish run does not match release tag commit")
        if not self.postmerge_ok({"merged": True, "merge_commit_sha": tag["sha"]}):
            fail("Release tag commit has no successful main push CI")
        metadata = obj(self.fetch(f"https://pypi.org/pypi/diwire/{version[1:]}/json"))
        files = rows(metadata["urls"])
        if str(obj(metadata["info"])["version"]) != version[1:]:
            fail("PyPI version does not match PATCH release")
        for kind, key in (("bdist_wheel", "wheel_sha256"), ("sdist", "sdist_sha256")):
            matching = [
                file for file in files if file.get("packagetype") == kind and not file.get("yanked")
            ]
            if not matching or any(
                obj(file["digests"])["sha256"] != receipts[key] for file in matching
            ):
                fail(f"PyPI {kind} hash does not match receipt")

    def validate_record(self, job: Job, args: argparse.Namespace) -> None:
        """Check exact PR identity and completion evidence."""
        if args.pr is not None:
            if args.pr < 1:
                fail("PR number must be positive")
            if job["pr"] and job["pr"] != args.pr:
                fail("Cannot replace a job PR")
            job["pr"] = args.pr
        if args.head_sha:
            job["head_sha"] = args.head_sha
        if (
            args.status in WAITING
            and job["kind"] == "daily"
            and (not job["pr"] or not job["head_sha"])
        ):
            fail("Waiting requires PR and head SHA")
        if args.status == "complete":
            self.validate_complete(job, args)

    @staticmethod
    def evidence_file(value: str) -> None:
        """Require a nonempty evidence file on this machine."""
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or not path.stat().st_size:
            fail("Complete requires a real nonempty absolute validation evidence file")

    def validate_complete(self, job: Job, args: argparse.Namespace) -> None:
        """Verify terminal success against current remote commit evidence."""
        if job["kind"] == "release":
            self.release_complete(args)
            return
        self.evidence_file(args.validation_evidence)
        receipts = dict(item.split("=", 1) for item in args.receipt)
        required = {"accepted_head_sha", "accepted_base_sha", "accepted_tree_sha", "merge_sha"}
        if required - receipts.keys() or not job["pr"]:
            fail("Complete requires accepted head/base/tree and merge SHA receipts")
        root = f"repos/{self.config.repository}"
        pr = obj(self.json(["gh", "api", f"{root}/pulls/{job['pr']}"]))
        if receipts.get("change_kind") in {"non_runtime", "automation_maintenance"}:
            self.validate_non_runtime(job, receipts, args.validation_evidence)
        elif not (args.measurement_run_url or self.has_evidence(job)):
            fail("Complete requires measured Linux CI evidence")
        if (
            receipts["accepted_head_sha"] != job["head_sha"]
            or str(obj(pr["head"])["sha"]) != job["head_sha"]
            or pr.get("merge_commit_sha") != receipts["merge_sha"]
            or not self.postmerge_ok(pr)
        ):
            fail("Complete requires exact-head merge and successful postmerge CI")
        merge = obj(self.json(["gh", "api", f"{root}/git/commits/{receipts['merge_sha']}"]))
        head = obj(self.json(["gh", "api", f"{root}/git/commits/{job['head_sha']}"]))
        parents = rows(merge["parents"])
        if (
            not parents
            or parents[0]["sha"] != receipts["accepted_base_sha"]
            or obj(merge["tree"])["sha"] != receipts["accepted_tree_sha"]
            or obj(head["tree"])["sha"] != receipts["accepted_tree_sha"]
        ):
            fail("Merged tree/base does not match the accepted measured head")

    def validate_non_runtime(self, job: Job, receipts: dict[str, str], evidence_path: str) -> None:
        """Verify the complete diff before waiving performance measurements."""
        evidence = obj(json.loads(Path(evidence_path).read_text()))
        maintenance = receipts.get("change_kind") == "automation_maintenance"
        if (
            evidence.get("change_kind")
            != ("automation_maintenance" if maintenance else "non_runtime")
            or evidence.get("head_sha") != job["head_sha"]
            or evidence.get("base_sha") != receipts["accepted_base_sha"]
            or evidence.get("example_validation") != "passed"
            or evidence.get("measurement_review") != "not_applicable"
        ):
            fail("Non-runtime completion requires exact-head example validation evidence")
        comparison = obj(
            self.json(
                [
                    "gh",
                    "api",
                    (
                        f"repos/{self.config.repository}/compare/"
                        f"{receipts['accepted_base_sha']}...{job['head_sha']}"
                    ),
                ]
            )
        )
        files = rows(comparison.get("files", []))
        if not files or len(files) >= COMPARE_FILE_LIMIT:
            fail("Non-runtime diff is empty or exceeds the complete comparison limit")
        if maintenance:
            self.validate_owner_maintenance(job, evidence, files)
        for file in files:
            for path in (file["filename"], file.get("previous_filename", file["filename"])):
                if not (
                    str(path).startswith(("examples/", "docs/", "tests/"))
                    or path == "README.md"
                    or (
                        maintenance
                        and (str(path).startswith(".bb/") or path == "tools/bb_perf_dispatch.py")
                    )
                ):
                    fail(f"Non-runtime completion includes an ineligible path: {path}")

    @staticmethod
    def validate_owner_maintenance(
        job: Job, evidence: dict[str, object], files: Sequence[Mapping[str, object]]
    ) -> None:
        """Bind an explicit owner update to root-owned, pinned acceptance code."""
        authorization_path = Path(str(evidence.get("owner_authorization_path", "")))
        storage_value = os.environ.get("BB_THREAD_STORAGE")
        if not storage_value:
            fail("Owner maintenance requires root-owned authorization and a pinned dispatcher")
        storage = Path(storage_value).resolve()
        verifier = Path(__file__).resolve()
        if (
            storage.name != job["thread_id"]
            or not authorization_path.is_absolute()
            or not authorization_path.resolve().is_relative_to(storage)
            or verifier.is_relative_to(Path(job["workspace"]).resolve())
        ):
            fail("Owner maintenance requires root-owned authorization and a pinned dispatcher")
        authorization = obj(json.loads(authorization_path.read_text()))
        paths = sorted(
            {
                str(path)
                for file in files
                for path in (file["filename"], file.get("previous_filename", file["filename"]))
            }
        )
        paths_hash = hashlib.sha256(
            json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        if (
            authorization.get("kind") != "owner_authorized_automation_maintenance"
            or authorization.get("root_thread_id") != job["thread_id"]
            or authorization.get("root_thread_id") != os.environ.get("BB_THREAD_ID")
            or not authorization.get("owner_request")
            or authorization.get("head_sha") != job["head_sha"]
            or authorization.get("base_sha") != evidence["base_sha"]
            or authorization.get("changed_paths_sha256") != paths_hash
            or authorization.get("dispatcher_sha256")
            != hashlib.sha256(verifier.read_bytes()).hexdigest()
        ):
            fail("Owner maintenance authorization does not match the exact update")


def parser() -> argparse.ArgumentParser:
    """Expose a small dependency-free controller interface."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True, type=Path)
    result.add_argument("--state-dir", required=True, type=Path)
    commands = result.add_subparsers(dest="command", required=True)
    tick = commands.add_parser("tick")
    tick.add_argument("--dry-run", action="store_true")
    tick.add_argument(
        "--now", type=datetime.fromisoformat, help="Aware ISO timestamp for schedule tests"
    )
    commands.add_parser("status")
    patch = commands.add_parser("patch-version")
    patch.add_argument("version")
    record = commands.add_parser("record")
    for name in ("job", "thread-id", "environment-id", "workspace"):
        record.add_argument(f"--{name}", required=True)
    record.add_argument("--status", choices=sorted(STATUSES), required=True)
    record.add_argument("--pr", type=int)
    record.add_argument("--reopen", action="store_true", help="Owner-requested failed-job resume")
    for name in ("head-sha", "validation-evidence", "measurement-run-url", "reason"):
        record.add_argument(f"--{name}", default="")
    record.add_argument("--receipt", action="append", default=[], help="Extra key=value evidence")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Print JSON status; expected waits succeed without waking an agent."""
    args = parser().parse_args(argv)
    try:
        if args.command == "patch-version":
            sys.stdout.write(patch_version(args.version) + "\n")
            return 0
        now = getattr(args, "now", None)
        if now is not None and not args.dry_run:
            fail("--now is restricted to --dry-run; live ticks use the system clock")
        if now is not None and now.tzinfo is None:
            fail("--now requires an explicit UTC offset")
        controller = Controller(
            args.config, args.state_dir, clock=(lambda: now) if now else utc_now
        )
        if args.command == "tick":
            output: object = controller.tick(dry_run=args.dry_run)
        elif args.command == "record":
            if os.environ.get("BB_THREAD_ID", args.thread_id) != args.thread_id:
                fail("Only the actual root BB_THREAD_ID may record this job")
            controller.record(args)
            output = {"recorded": args.job, "status": args.status}
        else:
            with controller.store.locked():
                output = controller.store.state
        sys.stdout.write(json.dumps(output, sort_keys=True) + "\n")
    except (
        DispatchError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        sys.stderr.write(f"bb_perf_dispatch: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
