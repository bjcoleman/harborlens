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

"""Text and JSON reports for a Harbor Lens assessment."""

import json
from datetime import timezone


def _day(value):
    if value is None:
        return "n/a"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _lead(minutes):
    if minutes is None:
        return "n/a"
    if minutes < 90:
        return "%.0f min" % minutes
    hours = minutes / 60
    if hours < 48:
        return "%.1f hours" % hours
    return "%.1f days" % (hours / 24)


def _per_week(value):
    if value is None:
        return "n/a"
    if value < 0.1:
        return "%.2f / week" % value
    return "%.1f / week" % value


LOCKED = [
    "Time to restore service",
    "Change failure rate",
    "Incidents labeled Incident, linked by \"root cause: <sha>\"",
    "Reviewer load balancing recommendations",
    "Benchmarks against 1,200+ engineering teams",
    "Step-by-step improvement plan",
]

NOT_MEASURED = "not measured in the free tool"


def render_text(repository, deploy_source, summary, notes, github_token="not found"):
    rows = [
        ("Deployment frequency", _per_week(summary["deploys_per_week"]), summary["frequency_band"]),
        ("Lead time for changes", _lead(summary["lead_minutes"]), summary["lead_band"]),
        ("Time to restore service", "n/a", NOT_MEASURED),
        ("Change failure rate", "n/a", NOT_MEASURED),
    ]
    label_width = max(len(row[0]) for row in rows)
    value_width = max(len(row[1]) for row in rows)
    token_line = "GitHub token: %s" % github_token

    lines = [
        "HARBOR LENS  |  Free Assessment",
        token_line,
        "Repository:  %s" % repository,
        "Period:      %s to %s" % (_day(summary["start"]), _day(summary["end"])),
        "Data:        %d commits, %d deployments"
        % (summary["commits"], summary["deployments"]),
        "Deploys:     %s" % deploy_source,
        "",
        "DORA METRICS",
    ]
    for label, value, band in rows:
        lines.append(
            "  %s  %s  %s" % (label.ljust(label_width), value.rjust(value_width), band)
        )

    if summary["lead_minutes"] is None and summary["deployments"]:
        lines.append("")
        lines.append(
            "Lead time ignores changes deployed in the same minute (METRICS.md)."
        )
    if summary["unmatched_deployments"]:
        lines.append(
            "%d deployment events had no matching commit and were not counted."
            % summary["unmatched_deployments"]
        )
    extra = [note for note in notes if note]
    if extra:
        lines.append("")
        lines.extend(extra)

    lines.extend(
        [
            "",
            "Not in this free report: incidents, pull requests, CI, and review load.",
            "",
            "HARBOR GLASS FULL ANALYSIS  (locked)",
        ]
    )
    lines.extend("  [x] %s" % item for item in LOCKED)
    lines.extend(["", "  Learn more: https://spiralharbor.com/glass", ""])
    return "\n".join(lines)


def render_json(repository, deploy_source, summary, notes, github_token="not found"):
    payload = {
        "github_token": github_token,
        "repository": repository,
        "deploy_source": deploy_source,
        "period": {"start": _day(summary["start"]), "end": _day(summary["end"])},
        "counts": {
            "commits": summary["commits"],
            "deployments": summary["deployments"],
        },
        "metrics": {
            "deployment_frequency": {
                "per_week": summary["deploys_per_week"],
                "band": summary["frequency_band"],
            },
            "lead_time_for_changes": {
                "median_minutes": summary["lead_minutes"],
                "band": summary["lead_band"],
            },
            "time_to_restore_service": {
                "median_hours": None,
                "band": None,
                "measured": False,
                "note": NOT_MEASURED,
            },
            "change_failure_rate": {
                "ratio": None,
                "band": None,
                "measured": False,
                "note": NOT_MEASURED,
            },
        },
        "notes": [note for note in notes if note],
        "harbor_glass": {
            "locked": list(LOCKED),
            "url": "https://spiralharbor.com/glass",
        },
    }
    return json.dumps(payload, indent=2) + "\n"
