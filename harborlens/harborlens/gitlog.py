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

"""Read commits and tags from a local git repository.

Four Keys counts a GitHub deployment only when the event type is
deployment_status and deployment_status.state is success
(queries/deployments.sql). Tags are not an event type. Harbor Lens turns
each tag into a deployment_status whose sha is the tagged commit, and a
push whose id is that same sha, so the view's join still works.

The push for a tag carries every first-parent commit after the previous
tag, up to and including the tagged commit. Lead time is then the time
from each of those commits to the tag. Annotated tags use the tagger
date. A lightweight tag has no tagger date, so its deploy time is the
tagged commit's timestamp: that commit's own lead time is zero and
METRICS.md drops it, while earlier commits in the release still count.
Tags that are not on the first parent of HEAD are ignored.
"""

import subprocess

from harborlens.metrics import parse_time


class GitError(Exception):
    pass


# A real unit separator. git log expands %x1f; for-each-ref does not.
_SEP = "\x1f"


def _git(repo, *args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitError(detail or "git %s failed" % " ".join(args)) from exc
    return completed.stdout


def ensure_repo(path):
    """Accept a working tree or a bare repository.

    GitHub URLs are cloned with ``git clone --bare``. A bare repository
    is a git repository, and ``--is-inside-work-tree`` reports false for it.
    """
    try:
        bare = _git(path, "rev-parse", "--is-bare-repository").strip()
        inside = _git(path, "rev-parse", "--is-inside-work-tree").strip()
    except GitError as exc:
        raise GitError("%s is not a git repository" % path) from exc
    if bare != "true" and inside != "true":
        raise GitError("%s is not a git repository" % path)


def read_history(repo):
    """Return (commits, tags) for the first parent of HEAD.

    commits is a chronological list of {"sha", "time"}.
    tags is a list of {"name", "commit", "time", "annotated"}.
    """
    ensure_repo(repo)
    raw_log = _git(
        repo,
        "log",
        "--first-parent",
        "--reverse",
        "--pretty=format:%H" + _SEP + "%aI",
    )
    commits = []
    for line in raw_log.splitlines():
        if not line.strip():
            continue
        sha, authored = line.split("\x1f", 1)
        commits.append({"sha": sha, "time": parse_time(authored)})

    if not commits:
        raise GitError("%s has no commits on HEAD" % repo)

    raw_tags = _git(
        repo,
        "for-each-ref",
        "refs/tags",
        "--format=%(refname:short)" + _SEP + "%(objecttype)" + _SEP + "%(objectname)"
        + _SEP + "%(*objectname)" + _SEP + "%(creatordate:iso-strict)"
        + _SEP + "%(*creatordate:iso-strict)",
    )
    tags = []
    for line in raw_tags.splitlines():
        if not line.strip():
            continue
        name, obj_type, obj_name, peeled, created, peeled_created = (
            line.split("\x1f") + [""] * 6
        )[:6]
        annotated = obj_type == "tag"
        commit = peeled if annotated and peeled else obj_name
        when = created if created else peeled_created
        if not commit or not when:
            continue
        tags.append(
            {
                "name": name,
                "commit": commit,
                "time": parse_time(when),
                "annotated": annotated,
            }
        )
    tags.sort(key=lambda tag: (tag["time"], tag["name"]))
    return commits, tags


def deployment_groups(commits, tags):
    """Group first-parent commits under the tag that deploys them.

    Yields {"tag", "head", "commits"} where head is the tagged commit and
    commits is the chronological list deployed by that tag. Tags whose
    commit is not on the first parent are skipped.
    """
    index = {commit["sha"]: position for position, commit in enumerate(commits)}
    by_sha = {commit["sha"]: commit for commit in commits}
    previous = -1
    seen = set()

    for tag in tags:
        if tag["commit"] in seen:
            continue
        seen.add(tag["commit"])
        if tag["commit"] not in index:
            continue
        position = index[tag["commit"]]
        if position <= previous:
            group = [by_sha[tag["commit"]]]
        else:
            group = commits[previous + 1 : position + 1]
            previous = position
        if not group:
            group = [by_sha[tag["commit"]]]
        yield {"tag": tag, "head": tag["commit"], "commits": group}


def push_payload(group):
    commits = [
        {"id": commit["sha"], "timestamp": commit["time"].strftime("%Y-%m-%dT%H:%M:%SZ")}
        for commit in group["commits"]
    ]
    head = next(item for item in commits if item["id"] == group["head"])
    return {
        "head_commit": head,
        "before": "0000000000000000000000000000000000000000",
        "commits": commits,
    }


def deployment_payload(group):
    tag = group["tag"]
    return {
        "deployment_status": {
            "updated_at": tag["time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "id": "tag-%s" % tag["name"],
            "state": "success",
        },
        "deployment": {"sha": group["head"]},
    }
