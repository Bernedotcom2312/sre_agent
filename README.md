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

- `get_alerts(time_range)` — active Cloud Monitoring alert policies
- `get_pod_logs(namespace, pod)` — recent pod logs (via Cloud Logging)
- `get_k8s_events(namespace)` — recent Kubernetes events (via Cloud Logging)
- `get_recent_deploys(namespace)` — recent deployments, to correlate deploy → incident (via
  Cloud Audit Logs)

## Tests

```bash
uv run pytest
```

## Provisioning a POC cluster

```bash
PROJECT_ID=<my-gcp-project> ./scripts/create-gke-cluster.sh
```

Provisions a minimal GKE cluster with Cloud Logging/Monitoring enabled and configures `kubectl`.

## Deploy to Agent Engine

The agent can be deployed to [Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/overview),
a managed, serverless hosting platform for ADK agents:

```bash
uv run adk deploy agent_engine sre_agent \
  --project=<my-gcp-project> \
  --region=<region> \
  --display_name="SRE Agent"
```

Notes:

- Requires the `aiplatform`, `artifactregistry`, `storage`, and `cloudbuild` APIs enabled on the
  target project.
- The deploy CLI builds a container image and pushes it to Agent Engine; after the "Dockerfile
  created at ..." line it goes silent while the build/deploy runs server-side — this can take
  5–15 minutes on a first deploy, with no further CLI output until it completes or fails.
- `sre_agent/requirements.txt` lists the extra runtime dependencies (`google-cloud-monitoring`,
  `google-cloud-logging`, `google-api-core`, `google-auth`) that the deploy CLI doesn't infer
  automatically from `pyproject.toml` — keep it in sync with `pyproject.toml` or the deployed
  container will fail to import the tools.
- `adk deploy agent_engine` only uses `GOOGLE_CLOUD_PROJECT` (from `.env` or `--project`) to pick
  the deploy target — it does **not** forward it as a runtime env var to the deployed agent.
  `tools.py` works around this by falling back to the project discovered via Application Default
  Credentials (`google.auth.default()`) when `GOOGLE_CLOUD_PROJECT` isn't set.

## Conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat: `, `fix: `, `chore: `, `docs: `, `refactor: `, `test: `). See [`CLAUDE.md`](CLAUDE.md)
for the full list of project constraints (read-only, credentials kept out of the repo, etc.).
