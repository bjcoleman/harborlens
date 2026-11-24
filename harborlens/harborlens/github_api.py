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

"""Recognize a GitHub repository URL.

The free assessment clones that URL with git. It does not call the
GitHub API. Incident lookup is a Harbor Glass feature, described in
the man page.
"""

import re

GITHUB_HTTP = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
GITHUB_SSH = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")


def parse_github_target(target):
    """Return (owner, repo) or None when target is not a GitHub URL."""
    for pattern in (GITHUB_HTTP, GITHUB_SSH):
        match = pattern.match(target.strip())
        if match:
            return match.group(1), match.group(2)
    return None
