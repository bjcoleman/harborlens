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

"""Command line for Harbor Lens."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harborlens.events import to_event, write_jsonl
from harborlens.gitlog import (
    GitError,
    deployment_groups,
    deployment_payload,
    push_payload,
    read_history,
)
from harborlens.github_api import parse_github_target
from harborlens.metrics import parse_time, summarize
from harborlens.report import render_json, render_text


ASSESS_SOURCE = "git tags normalized to deployment_status events"


def _add_output_args(parser):
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="report format (default: text)",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="write events_raw rows as JSONL to FILE",
    )
    parser.add_argument(
        "--since",
        metavar="DATE",
        help="ignore events before DATE (YYYY-MM-DD)",
    )


def _parser():
    parser = argparse.ArgumentParser(
        prog="harborlens",
        description="Free DORA assessment. assess reads a git repository's commits and tags.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    assess = commands.add_parser(
        "assess",
        help="assess a local git repository or a GitHub URL",
    )
    assess.add_argument(
        "target",
        help="path to a git repo, or https://github.com/owner/repo",
    )
    _add_output_args(assess)
    return parser


def _display_env_path(env_file):
    """Path of a .env file relative to the working directory, for the report."""
    relative = os.path.relpath(env_file, Path.cwd())
    if relative == ".env":
        return "./.env"
    if not relative.startswith("."):
        return "./" + relative
    return relative


def _github_token_status():
    """Where GITHUB_TOKEN came from. Never includes the token value.

    A non-empty value already in the environment wins over the file.
    Otherwise the status names the .env file that supplied it.
    """
    already = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    env_file = _load_env()
    present = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    if not present:
        return "not found"
    if already or env_file is None:
        return "found in environment"
    return "found %s" % _display_env_path(env_file)


def _emit(repository, deploy_source, events, args, notes):
    summary = summarize(events, since=args.since)
    token_status = _github_token_status()
    if args.format == "json":
        text = render_json(repository, deploy_source, summary, notes, token_status)
    else:
        text = render_text(repository, deploy_source, summary, notes, token_status)
    sys.stdout.write(text)
    if args.output:
        chosen = events
        if args.since:
            cutoff = parse_time(args.since)
            chosen = [event for event in events if parse_time(event["time_created"]) >= cutoff]
        write_jsonl(chosen, args.output)


def _prepare_checkout(target):
    """Return (repo_path, cleanup, github_slug).

    A GitHub URL is cloned bare into a temporary directory. A local path
    is used in place.
    """
    slug = parse_github_target(target)
    local = Path(target)
    if slug is None and local.exists():
        return local.resolve(), None, None
    if slug is None:
        raise GitError(
            "Give a path to a local git repository, or a URL like "
            "https://github.com/owner/repo"
        )

    temporary = tempfile.mkdtemp(prefix="harborlens-")
    destination = Path(temporary) / "repo.git"
    try:
        subprocess.run(
            ["git", "clone", "--bare", "--quiet", target, str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitError(detail or "git clone failed") from exc
    return destination, temporary, "%s/%s" % slug


def _single_push(commit):
    stamp = commit["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "head_commit": {"id": commit["sha"], "timestamp": stamp},
        "before": "0000000000000000000000000000000000000000",
        "commits": [{"id": commit["sha"], "timestamp": stamp}],
    }


def _assess_events(repo):
    commits, tags = read_history(repo)
    on_head = {commit["sha"] for commit in commits}
    groups = list(deployment_groups(commits, tags))
    events = []
    covered = set()
    for index, group in enumerate(groups, start=1):
        for commit in group["commits"]:
            covered.add(commit["sha"])
        events.append(to_event("push", push_payload(group), "assess-push-%d" % index))
        events.append(
            to_event(
                "deployment_status",
                deployment_payload(group),
                "assess-deploy-%d" % index,
            )
        )
    extra = 0
    for commit in commits:
        if commit["sha"] in covered:
            continue
        extra += 1
        events.append(to_event("push", _single_push(commit), "assess-commit-%d" % extra))

    notes = []
    if not tags:
        notes.append(
            "No git tags found, so there are no deployments to score. "
            "Annotated tags are the deployment signal this free tool uses."
        )
    else:
        on_branch = [tag for tag in tags if tag["commit"] in on_head]
        lightweight = sum(1 for tag in on_branch if not tag["annotated"])
        if lightweight:
            notes.append(
                "%d of %d tags on HEAD are lightweight, so the deploy time is "
                "the tagged commit's timestamp."
                % (lightweight, len(on_branch))
            )
        off_branch = [tag for tag in tags if tag["commit"] not in on_head]
        if off_branch:
            notes.append(
                "%d tags are not on the first parent of HEAD and were not counted."
                % len(off_branch)
            )
    return events, notes


def _command_assess(args):
    repo, cleanup, slug = _prepare_checkout(args.target)
    try:
        events, notes = _assess_events(repo)
        name = slug if slug is not None else Path(repo).name
        _emit(name, ASSESS_SOURCE, events, args, notes)
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


def _env_search_dirs():
    """Directories to check for a .env file.

    Inside a git checkout, search from the working directory up through
    the repository root and stop there. Outside a checkout, check only
    the working directory.
    """
    cwd = Path.cwd()
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return [cwd]
    root = Path(top)
    directories = []
    for directory in [cwd, *cwd.parents]:
        directories.append(directory)
        if directory == root:
            break
    return directories


def _load_env():
    """Read a .env file if one is present.

    A variable already set in the environment is left alone, so a shell
    export overrides the file.
    """
    env_file = None
    for directory in _env_search_dirs():
        candidate = directory / ".env"
        if candidate.is_file():
            env_file = candidate
            break
    if env_file is None:
        return None
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise SystemExit(
            "harborlens: found %s but python-dotenv is not installed. "
            "Reinstall with: pip install -e harborlens" % env_file
        ) from exc
    load_dotenv(env_file, override=False)
    return env_file


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        _command_assess(args)
    except GitError as exc:
        sys.stderr.write("harborlens: %s\n" % exc)
        return 1
    except ValueError as exc:
        sys.stderr.write("harborlens: %s\n" % exc)
        return 1
    return 0


def console_main():
    """Entry point for the installed harborlens command."""
    raise SystemExit(main())


if __name__ == "__main__":
    sys.exit(main())
