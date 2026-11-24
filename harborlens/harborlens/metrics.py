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

"""Deployment frequency and lead time from events_raw rows.

What counts as a change or a deployment follows queries/changes.sql and
queries/deployments.sql. The time window is the span of the events (or
--since), not the last three months from today used by the dashboard
queries in METRICS.md. Bucket names match that file.

Time to restore and change failure rate need incidents. The free report
does not measure them. They are listed in the locked Harbor Glass section.
"""

import json
from datetime import datetime, timedelta, timezone


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        parsed = datetime.fromtimestamp(int(value), timezone.utc)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metadata(event):
    raw = event.get("metadata")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def _github(event):
    return str(event.get("source", "")).startswith("github")


def changes_by_id(events):
    """Commit id -> timestamp, from push events. See queries/changes.sql."""
    found = {}
    for event in events:
        if event.get("event_type") != "push" or not _github(event):
            continue
        for commit in _metadata(event).get("commits") or []:
            commit_id = commit.get("id")
            timestamp = commit.get("timestamp")
            if commit_id and timestamp is not None and commit_id not in found:
                found[commit_id] = parse_time(timestamp)
    return found


def deployments(events):
    """Successful GitHub deployment_status events joined to a push.

    The join matches queries/deployments.sql: the push row id equals
    deployment.sha. The changes are the commits on that push.
    """
    pushes = {
        event["id"]: event
        for event in events
        if event.get("event_type") == "push" and _github(event)
    }
    found = []
    skipped = 0
    for event in events:
        if event.get("event_type") != "deployment_status" or not _github(event):
            continue
        meta = _metadata(event)
        state = (meta.get("deployment_status") or {}).get("state")
        if state != "success":
            continue
        sha = (meta.get("deployment") or {}).get("sha")
        push = pushes.get(sha)
        if push is None:
            skipped += 1
            continue
        commit_ids = []
        for commit in _metadata(push).get("commits") or []:
            if commit.get("id"):
                commit_ids.append(commit["id"])
        found.append(
            {
                "id": event["id"],
                "time": parse_time(event["time_created"]),
                "sha": sha,
                "changes": commit_ids,
            }
        )
    return found, skipped


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _days(start, end):
    day = start.date()
    last = end.date()
    while day <= last:
        yield day
        day += timedelta(days=1)


def _next_month(day):
    if day.month == 12:
        return day.replace(year=day.year + 1, month=1)
    return day.replace(month=day.month + 1)


def frequency(deploys, start, end):
    """Return (per_week, band) using the METRICS.md thresholds."""
    if not deploys or start is None or end is None:
        return None, "n/a"

    deploy_days = {deploy["time"].date() for deploy in deploys}
    weeks = {}
    for day in _days(start, end):
        week_start = day - timedelta(days=(day.weekday() + 1) % 7)
        weeks.setdefault(week_start, []).append(day)

    days_deployed = []
    week_has = []
    for days in weeks.values():
        count = sum(1 for day in days if day in deploy_days)
        days_deployed.append(count)
        week_has.append(1 if count else 0)

    per_month = {}
    for deploy in deploys:
        key = (deploy["time"].year, deploy["time"].month)
        per_month[key] = per_month.get(key, 0) + 1
    month_counts = []
    cursor = start.date().replace(day=1)
    last = end.date().replace(day=1)
    while cursor <= last:
        month_counts.append(per_month.get((cursor.year, cursor.month), 0))
        cursor = _next_month(cursor)

    med_days = _median(days_deployed)
    med_weeks = _median(week_has)
    med_months = _median(month_counts)
    if med_days is not None and med_days >= 3:
        band = "Daily"
    elif med_weeks is not None and med_weeks >= 1:
        band = "Weekly"
    elif med_months is not None and med_months >= 1:
        band = "Monthly"
    else:
        band = "Yearly"

    per_week = len(deploys) / max(len(weeks), 1)
    return per_week, band


def lead_time_band(minutes):
    if minutes is None:
        return "n/a"
    if minutes < 24 * 60:
        return "One day"
    if minutes < 168 * 60:
        return "One week"
    if minutes < 730 * 60:
        return "One month"
    if minutes < 730 * 6 * 60:
        return "Six months"
    return "One year"


def _window(events, since):
    times = [parse_time(event["time_created"]) for event in events if event.get("time_created") is not None]
    if since:
        cutoff = parse_time(since)
        times = [item for item in times if item >= cutoff]
        if not times:
            return cutoff, cutoff
        return cutoff, max(times)
    if not times:
        return None, None
    return min(times), max(times)


def filter_since(events, since):
    if not since:
        return events
    cutoff = parse_time(since)
    return [event for event in events if parse_time(event["time_created"]) >= cutoff]


def summarize(events, since=None):
    """Return the numbers the report prints."""
    chosen = filter_since(events, since)
    start, end = _window(chosen, since)
    commits = changes_by_id(chosen)
    deploys, skipped = deployments(chosen)

    samples = []
    commit_times = commits
    for deploy in deploys:
        for commit_id in deploy["changes"]:
            committed = commit_times.get(commit_id)
            if committed is None:
                continue
            minutes = (deploy["time"] - committed).total_seconds() / 60
            if minutes > 0:
                samples.append(minutes)
    median_lead = _median(samples)
    per_week, freq_band = frequency(deploys, start, end)

    return {
        "start": start,
        "end": end,
        "commits": len(commits),
        "deployments": len(deploys),
        "unmatched_deployments": skipped,
        "deploys_per_week": per_week,
        "frequency_band": freq_band,
        "lead_minutes": median_lead,
        "lead_band": lead_time_band(median_lead),
    }
