# SRE Agent

An incident-diagnosis copilot for GKE built on [Google ADK](https://google.github.io/adk-docs/).
The agent correlates Cloud Monitoring alerts, logs, and Kubernetes events to suggest a probable
root cause, a timeline, and a draft postmortem — the goal is to reduce MTTR (a DORA metric).
See [`todo.md`](todo.md) for the detailed plan and [`CLAUDE.md`](CLAUDE.md) for project
conventions.

## Stack

- **Agent framework**: Google ADK (Python)
- **Data sources**: Cloud Monitoring (alerts), Cloud Logging, Kubernetes events
- **Deployment target**: GKE or Agent Engine
- **Dependency management**: [uv](https://docs.astral.sh/uv/)

## Project structure

```
sre_agent/
├── sre_agent/
│   ├── agent.py       # root_agent definition (model, instruction, tools)
│   └── tools.py        # read-only tools: get_alerts, get_pod_logs,
│                        # get_k8s_events, get_recent_deploys
├── tests/
│   └── test_tools.py   # unit tests (get_alerts)
├── scripts/
│   └── create-gke-cluster.sh  # provisions a POC GKE cluster
├── pyproject.toml / uv.lock    # pinned dependencies
└── todo.md              # plan and roadmap
```

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A GCP project with the Cloud Monitoring / Logging APIs enabled
- `gcloud auth application-default login` for local GCP library authentication

## Install

```bash
uv sync
```

This creates the `.venv` and installs the exact dependencies pinned in `uv.lock`.

## Configuration

Create a `.env` file at the repo root (never committed, see `.gitignore`) with at least:

```
GOOGLE_CLOUD_PROJECT=<my-gcp-project>
GOOGLE_CLOUD_LOCATION=<region>
GOOGLE_GENAI_USE_ENTERPRISE=<true|false>
```

## Run the agent locally

```bash
uv run adk web
```

Opens the ADK web interface to chat with the agent and watch tool calls live.

## Available tools

All tools are **read-only** — the agent diagnoses, it never acts on the cluster:

- `get_alerts(time_range)` — active Cloud Monitoring alert policies (wired to the real API)
- `get_pod_logs(namespace, pod)` — recent pod logs (mocked)
- `get_k8s_events(namespace)` — recent Kubernetes events (mocked)
- `get_recent_deploys(namespace)` — recent deployments, to correlate deploy → incident (mocked)

## Tests

```bash
uv run pytest
```

## Provisioning a POC cluster

```bash
PROJECT_ID=<my-gcp-project> ./scripts/create-gke-cluster.sh
```

Provisions a minimal GKE cluster with Cloud Logging/Monitoring enabled and configures `kubectl`.

## Conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat: `, `fix: `, `chore: `, `docs: `, `refactor: `, `test: `). See [`CLAUDE.md`](CLAUDE.md)
for the full list of project constraints (read-only, credentials kept out of the repo, etc.).
