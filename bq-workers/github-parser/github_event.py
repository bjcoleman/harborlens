# Copyright 2020 Google LLC
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

# Modified by Spiral Harbor.
# Extracted from main.py so local tools can parse GitHub events without
# importing Flask or BigQuery.

import base64
import json


def process_github_event(headers, msg):
    event_type = headers["X-Github-Event"]
    signature = headers["X-Hub-Signature"]
    source = "github"

    if "Mock" in headers:
        source += "mock"

    types = {"push", "pull_request", "pull_request_review",
             "pull_request_review_comment", "issues",
             "issue_comment", "check_run", "check_suite", "status",
             "deployment_status", "release"}

    if event_type not in types:
        raise Exception("Unsupported GitHub event: '%s'" % event_type)

    metadata = json.loads(base64.b64decode(msg["data"]).decode("utf-8").strip())

    if event_type == "push":
        time_created = metadata["head_commit"]["timestamp"]
        e_id = metadata["head_commit"]["id"]

    if event_type == "pull_request":
        time_created = metadata["pull_request"]["updated_at"]
        e_id = metadata["repository"]["name"] + "/" + str(metadata["number"])

    if event_type == "pull_request_review":
        time_created = metadata["review"]["submitted_at"]
        e_id = metadata["review"]["id"]

    if event_type == "pull_request_review_comment":
        time_created = metadata["comment"]["updated_at"]
        e_id = metadata["comment"]["id"]

    if event_type == "issues":
        time_created = metadata["issue"]["updated_at"]
        e_id = metadata["repository"]["name"] + "/" + str(metadata["issue"]["number"])

    if event_type == "issue_comment":
        time_created = metadata["comment"]["updated_at"]
        e_id = metadata["comment"]["id"]

    if event_type == "check_run":
        time_created = (metadata["check_run"]["completed_at"] or
                        metadata["check_run"]["started_at"])
        e_id = metadata["check_run"]["id"]

    if event_type == "check_suite":
        time_created = (metadata["check_suite"]["updated_at"] or
                        metadata["check_suite"]["created_at"])
        e_id = metadata["check_suite"]["id"]

    if event_type == "deployment_status":
        time_created = metadata["deployment_status"]["updated_at"]
        e_id = metadata["deployment_status"]["id"]

    if event_type == "status":
        time_created = metadata["updated_at"]
        e_id = metadata["id"]

    if event_type == "release":
        time_created = (metadata["release"]["published_at"] or
                        metadata["release"]["created_at"])
        e_id = metadata["release"]["id"]

    github_event = {
        "event_type": event_type,
        "id": e_id,
        "metadata": json.dumps(metadata),
        "time_created": time_created,
        "signature": signature,
        "msg_id": msg["message_id"],
        "source": source,
    }

    return github_event
