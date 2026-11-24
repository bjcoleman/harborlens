# Copyright Spiral Harbor
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harborlens.cli import main
from harborlens.events import to_event
from harborlens.gitlog import deployment_groups, read_history
from harborlens.metrics import summarize

PARSER_DIR = Path(__file__).resolve().parents[1] / "bq-workers" / "github-parser"


def _git(repo, *args, date=None):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Harbor Lens Test"
    env["GIT_AUTHOR_EMAIL"] = "harborlens-test@example.com"
    env["GIT_COMMITTER_NAME"] = "Harbor Lens Test"
    env["GIT_COMMITTER_EMAIL"] = "harborlens-test@example.com"
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    try:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AssertionError("git %s failed: %s" % (" ".join(args), detail)) from exc


def _iso(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(argv):
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


def test_parser_module_has_no_cloud_imports():
    source = (PARSER_DIR / "github_event.py").read_text(encoding="utf-8")
    assert "bigquery" not in source
    assert "import flask" not in source.lower()
    assert "from flask" not in source.lower()
    assert "import shared" not in source


def test_process_github_event_matches_the_worker_fixture():
    sys.path.insert(0, str(PARSER_DIR))
    from github_event import process_github_event

    headers = {"X-Github-Event": "push", "X-Hub-Signature": "foo"}
    body = json.dumps({"head_commit": {"timestamp": 0, "id": "bar"}}).encode("utf-8")
    event = process_github_event(
        headers,
        {"data": base64.b64encode(body).decode("utf-8"), "message_id": "foobar"},
    )
    assert event["id"] == "bar"
    assert event["source"] == "github"
    assert event["time_created"] == 0
    assert event["event_type"] == "push"


def test_views_on_a_hand_built_history():
    push = to_event(
        "push",
        {
            "head_commit": {"id": "aaa", "timestamp": _iso(2026, 1, 1)},
            "commits": [
                {"id": "bbb", "timestamp": _iso(2025, 12, 31)},
                {"id": "aaa", "timestamp": _iso(2026, 1, 1)},
            ],
        },
        "push-1",
    )
    deploy = to_event(
        "deployment_status",
        {
            "deployment_status": {
                "updated_at": _iso(2026, 1, 3),
                "id": "d1",
                "state": "success",
            },
            "deployment": {"sha": "aaa"},
        },
        "deploy-1",
    )
    summary = summarize([push, deploy])
    assert summary["commits"] == 2
    assert summary["deployments"] == 1
    # 31 Dec and 1 Jan, deployed 3 Jan: median of 3 days and 2 days.
    assert summary["lead_minutes"] == pytest.approx(2.5 * 24 * 60)
    assert summary["lead_band"] == "One week"


def test_zero_minute_lead_time_is_dropped():
    push = to_event(
        "push",
        {
            "head_commit": {"id": "ccc", "timestamp": _iso(2026, 3, 1)},
            "commits": [{"id": "ccc", "timestamp": _iso(2026, 3, 1)}],
        },
        "push-z",
    )
    deploy = to_event(
        "deployment_status",
        {
            "deployment_status": {
                "updated_at": _iso(2026, 3, 1),
                "id": "d0",
                "state": "success",
            },
            "deployment": {"sha": "ccc"},
        },
        "deploy-z",
    )
    summary = summarize([push, deploy])
    assert summary["deployments"] == 1
    assert summary["lead_minutes"] is None
    assert summary["lead_band"] == "n/a"


def _empty_repo(path):
    _git(path, "init", "-b", "main")
    _git(path, "commit", "--allow-empty", "-m", "one", date="2026-01-01T00:00:00Z")


def _build_fixture(repo):
    _git(repo, "init", "-b", "main")
    _git(repo, "commit", "--allow-empty", "-m", "one", date="2026-01-01T00:00:00Z")
    _git(repo, "commit", "--allow-empty", "-m", "two", date="2026-01-10T00:00:00Z")
    second = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    _git(repo, "commit", "--allow-empty", "-m", "three", date="2026-01-20T00:00:00Z")
    third = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    _git(repo, "tag", "-a", "v1", second, "-m", "v1", date="2026-01-15T00:00:00Z")
    _git(repo, "tag", "-a", "v2", third, "-m", "v2", date="2026-02-01T00:00:00Z")


def test_annotated_tags_become_deployments():
    scratch = Path(__file__).resolve().parent / ".test-repos"
    scratch.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            repo = Path(temporary)
            _build_fixture(repo)

            commits, tags = read_history(repo)
            assert len(commits) == 3
            groups = list(deployment_groups(commits, tags))
            assert len(groups) == 2
            assert [commit["sha"] for commit in groups[0]["commits"]] == [
                commits[0]["sha"],
                commits[1]["sha"],
            ]
            assert [commit["sha"] for commit in groups[1]["commits"]] == [commits[2]["sha"]]

            code, text = _run(["assess", str(repo), "--format", "json"])
            assert code == 0
            report = json.loads(text)
            assert report["counts"]["commits"] == 3
            assert report["counts"]["deployments"] == 2
            assert "incidents" not in report["counts"]
            assert any(
                "Incidents labeled Incident" in item for item in report["harbor_glass"]["locked"]
            )
            lead = report["metrics"]["lead_time_for_changes"]
            assert lead["band"] == "One month"
            assert lead["median_minutes"] == pytest.approx(12 * 24 * 60)
            assert report["metrics"]["deployment_frequency"]["band"] == "Monthly"
            restore = report["metrics"]["time_to_restore_service"]
            failure = report["metrics"]["change_failure_rate"]
            assert restore["measured"] is False
            assert failure["measured"] is False
            assert restore["note"] == "not measured in the free tool"
            assert failure["note"] == "not measured in the free tool"

            bare = Path(temporary) / "fixture.git"
            subprocess.run(
                ["git", "clone", "--bare", "--quiet", str(repo), str(bare)],
                check=True,
                capture_output=True,
                text=True,
            )
            bare_code, bare_text = _run(["assess", str(bare), "--format", "json"])
            assert bare_code == 0
            bare_report = json.loads(bare_text)
            assert bare_report["counts"]["commits"] == 3
            assert bare_report["counts"]["deployments"] == 2
    finally:
        if scratch.exists() and not any(scratch.iterdir()):
            scratch.rmdir()


def test_assess_command_prints_the_report(monkeypatch, tmp_path):
    monkeypatch.setattr("harborlens.cli._load_env", lambda: None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _empty_repo(tmp_path)
    code, text = _run(["assess", str(tmp_path)])
    assert code == 0
    assert "HARBOR LENS" in text
    assert "GitHub token: not found" in text
    assert "Deployment frequency" in text
    assert "Time to restore service" in text
    assert "Change failure rate" in text
    assert text.count("not measured in the free tool") == 2
    assert "HARBOR GLASS FULL ANALYSIS" in text
    assert "Incidents labeled Incident" in text
    assert "https://spiralharbor.com/glass" in text


def test_report_names_the_env_file_without_printing_the_token(monkeypatch, tmp_path):
    secret = "ghp_from_file_should_not_appear"
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=%s\n" % secret, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _empty_repo(tmp_path)
    code, text = _run(["assess", "."])
    assert code == 0
    assert "GitHub token: found ./.env" in text
    assert secret not in text


def test_report_says_a_github_token_was_found_without_printing_it(monkeypatch, tmp_path):
    secret = "ghp_should_not_appear_in_the_report"
    monkeypatch.setattr("harborlens.cli._load_env", lambda: None)
    monkeypatch.setenv("GITHUB_TOKEN", secret)
    _empty_repo(tmp_path)
    code, text = _run(["assess", str(tmp_path), "--format", "json"])
    assert code == 0
    assert secret not in text
    report = json.loads(text)
    assert report["github_token"] == "found in environment"
    assert secret not in report["github_token"]
