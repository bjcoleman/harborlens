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

"""Turn webhook-shaped payloads into events_raw rows.

The row schema is the one in setup/events_raw_schema.json. Parsing is
process_github_event from the GitHub worker. That function expects a
Pub/Sub message: headers, plus base64-encoded JSON in msg["data"].
"""

import base64
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_DIR = REPO_ROOT / "bq-workers" / "github-parser"

SECRET = b"harborlens"


def _parser():
    parser_dir = str(PARSER_DIR)
    if parser_dir not in sys.path:
        sys.path.insert(0, parser_dir)
    from github_event import process_github_event

    return process_github_event


def isoformat(value):
    """UTC timestamp string. Naive datetimes are read as local time."""
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode(payload):
    def default(obj):
        if isinstance(obj, datetime):
            return isoformat(obj)
        raise TypeError("Cannot encode %s" % type(obj).__name__)

    return json.dumps(payload, default=default).encode("utf-8")


def to_event(event_type, payload, message_id, mock=False):
    """Parse one GitHub webhook body into an events_raw row."""
    body = _encode(payload)
    digest = hmac.new(SECRET, body, hashlib.sha1).hexdigest()
    headers = {
        "X-Github-Event": event_type,
        "X-Hub-Signature": "sha1=" + digest,
    }
    if mock:
        headers["Mock"] = True
    message = {
        "data": base64.b64encode(body).decode("utf-8"),
        "message_id": message_id,
    }
    return _parser()(headers, message)


def write_jsonl(events, path):
    destination = Path(path)
    with destination.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
