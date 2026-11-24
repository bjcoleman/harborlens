
## Overview

Harbor Lens is an assessment tool created by [Spiral Harbor](https://spiralharbor.com) that reports the [four DORA metrics](https://cloud.google.com/blog/products/devops-sre/using-the-four-keys-to-measure-your-devops-performance) for a git repo:

- **Deployment frequency** is how often a change reaches production.
- **Lead time for changes** is how long a commit waits before it is released.
- **Time to restore service** is how long it takes to recover after a release causes a failure.
- **Change failure rate** is the share of releases that cause a failure.


These delivery measures show how quickly and how safely a team gets software into production, and they are one of many metrics that [Harbor Glass](https://spiralharbor.com/glass) uses to help your team identify improvements to your delivery process.

The free version of the `harborlens` tool provides a portion of a DORA report so your team can start to understand the power of Harbor Glass.


## Prerequisites

Python 3.9 or newer, and `git`.

## Install

From the repository root on Mac or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e harborlens
```

On Windows, in PowerShell, from the same directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e harborlens
```


## Configuration

A GitHub token is optional for the free command, but recommended for the paid version. The full collector described in the man page uses the token to utilize the Github API to gather additional information.  A personal access token raises the hourly limit from 50 to 5,000.

To add a token, put it in a `.env` file at the root of this clone. The file is gitignored.

```text
GITHUB_TOKEN=ghp_...
```

`harborlens` reads that file on startup, from the directory where you run it or from a parent directory up through the git root. A `GITHUB_TOKEN` already set in the shell wins over the file.


## Running the tool

You can run `harborlens` on a local repo or a repo hosted on Github.  For a local repo, use:

```bash
harborlens assess <path to repo>
```

For example, the analysis of this repo (`harborlen assess .`) produces:

```text
HARBOR LENS  |  Free Assessment
GitHub token: found ./.env
Repository:  harborlens
Period:      2020-07-08 to 2024-01-24
Data:        224 commits, 210 deployments
Deploys:     git tags normalized to deployment_status events

DORA METRICS
  Deployment frequency     1.1 / week  Monthly
  Lead time for changes    12.0 hours  One day
  Time to restore service         n/a  not measured in the free tool
  Change failure rate             n/a  not measured in the free tool

5 of 210 tags on HEAD are lightweight, so the deploy time is the tagged commit's timestamp.

Not in this free report: incidents, pull requests, CI, and review load.

HARBOR GLASS FULL ANALYSIS  (locked)
  [x] Time to restore service
  [x] Change failure rate
  [x] Incidents labeled Incident, linked by "root cause: <sha>"
  [x] Reviewer load balancing recommendations
  [x] Benchmarks against 1,200+ engineering teams
  [x] Step-by-step improvement plan

  Learn more: https://spiralharbor.com/glass
```


You can also tell `harborlens` to analysis a repo hosted at Github:

```bash
harborlens assess <Github repo URL>
```

The tool will clone the repo to a temporary directory, which is deleted after the report is generated.


## Options

The `harborlens` tool supports a variety of options:

* `--output` - writes one JSON object per line. The fields are the `events_raw` columns: `event_type`, `id`, `metadata`, `time_created`, `signature`, `msg_id`, `source`.

* `--format` - chooses the report layout. `text` is the default and prints the report shown above. `json` prints the same assessment as one JSON object. 

* `--since` - drops events before that date. Use `YYYY-MM-DD`.


## The full tool

This version of Harbor Lens contains the man page for the full tool. On Mac or Linux you can install that page and then read it with `man harborlens`.

To install:

```bash
sudo mkdir -p /usr/local/share/man/man1
sudo cp harborlens/man/harborlens.1 /usr/local/share/man/man1/harborlens.1
man harborlens
```

If Linux says there is no entry, refresh the index and try again:

```bash
sudo mandb
man harborlens
```

## Harbor Glass

The report from this version is the first look. [Harbor Glass](https://spiralharbor.com/glass) is where those results, and the rest of what Spiral Harbor measures, turn into a prediction and a plan for your delivery process.

Contact sales at Spiral Harbor: [sales@spiralharbor.com](mailto:sales@spiralharbor.com) to arrange a full demo of [Harbor Glass](https://spiralharbor.com/glass).
