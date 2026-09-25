# SRE Agent

An incident-diagnosis copilot for GKE built on [Google ADK](https://google.github.io/adk-docs/).
The agent correlates Cloud Monitoring alerts, logs, and Kubernetes events to suggest a probable
root cause, a timeline, and a draft postmortem — the goal is to reduce MTTR (a DORA metric).
See [`CLAUDE.md`](CLAUDE.md) for project conventions.

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
├── slack_bot/
│   └── app.py           # Slack Events API front end, queries Agent Engine
├── manifests/
│   ├── toto/             # sample workload manifests for the POC cluster
│   └── tata/
├── tests/
│   ├── test_tools.py    # unit tests (agent tools)
│   └── test_slack_bot.py # unit tests (Slack bot)
├── scripts/
│   ├── create-gke-cluster.sh          # provisions a POC GKE cluster
│   └── deploy-slack-bot-cloud-run.sh  # deploys the Slack bot to Cloud Run
└── pyproject.toml / uv.lock    # pinned dependencies
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

- `get_alerts(time_range)` — Cloud Monitoring alert policies configured on the project (the API
  exposes no list of currently firing alerts, so this says what is monitored, not what is broken)
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
- The deployed agent runs as a service account, and **that** is what actually makes it read-only:
  the tools query nothing but Cloud Logging and Cloud Monitoring, so `roles/logging.viewer` and
  `roles/monitoring.viewer` are all it needs. Grant those two and nothing else — if the agent's
  identity keeps a role like Editor, the read-only guarantee in `CLAUDE.md` rests on the code
  alone, and a future tool (or a prompt injected through a log line it reads) could act on the
  cluster:

  ```bash
  AGENT_SA=<the service account shown on the Agent Engine instance>
  for role in roles/logging.viewer roles/monitoring.viewer; do
    gcloud projects add-iam-policy-binding <my-gcp-project> \
      --member "serviceAccount:${AGENT_SA}" --role "$role" --condition=None
  done
  ```

- `adk deploy agent_engine` only uses `GOOGLE_CLOUD_PROJECT` (from `.env` or `--project`) to pick
  the deploy target — it does **not** forward it as a runtime env var to the deployed agent.
  `tools.py` works around this by falling back to the project discovered via Application Default
  Credentials (`google.auth.default()`) when `GOOGLE_CLOUD_PROJECT` isn't set.

## Slack interface

Once the agent is deployed to Agent Engine (see above), you can query it from Slack instead of
`adk web`. `slack_bot/app.py` is a small Flask HTTP service that receives Slack's
[Events API](https://api.slack.com/apis/events-api) callbacks (`app_mention`), forwards the
message to the deployed agent, and posts the reply back in the same thread (each thread keeps its
own Agent Engine session, so the agent remembers earlier turns in it). The bot only forwards
text; it never touches GCP/GKE directly, and the agent's own tools stay read-only.

It's meant to run on **Cloud Run with `min-instances=0`**: with no traffic there's no running
container, so cost stays near zero between mentions (see
`scripts/deploy-slack-bot-cloud-run.sh`). This needs a public HTTPS URL (unlike Socket Mode),
secured by verifying Slack's request signature (`SLACK_SIGNING_SECRET`) rather than by
authenticating the endpoint itself — that's why the Cloud Run service is deployed with
`--allow-unauthenticated`.

### 1. Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
   Name it (e.g. "SRE Agent") and pick your workspace.
2. **OAuth & Permissions** → under **Scopes → Bot Token Scopes**, add `app_mentions:read` and
   `chat:write`.
3. **Install App** (left sidebar) → **Install to Workspace** → approve. Copy the **Bot User OAuth
   Token** (starts with `xoxb-`); this is your `SLACK_BOT_TOKEN`.
4. **Basic Information** → **App Credentials** → copy the **Signing Secret**; this is your
   `SLACK_SIGNING_SECRET`.
5. Deploy the bot first (step 2 below) so you have a URL — Slack verifies the Event Subscriptions
   URL live when you save it.
6. **Event Subscriptions** → toggle **on** → **Request URL**: `<cloud-run-url>/slack/events`
   (Slack calls it immediately; the bot must already be deployed and answer the verification
   challenge). Under **Subscribe to bot events**, add `app_mention`, then save.
7. Invite the bot to a channel: `/invite @SRE Agent`.

### 2. Deploy

```bash
PROJECT_ID=<my-gcp-project> \
AGENT_ENGINE_LOCATION=<region> \
AGENT_ENGINE_RESOURCE_NAME=projects/<project-number>/locations/<region>/reasoningEngines/<id> \
SLACK_BOT_TOKEN=xoxb-... \
SLACK_SIGNING_SECRET=... \
./scripts/deploy-slack-bot-cloud-run.sh
```

`AGENT_ENGINE_RESOURCE_NAME` is printed at the end of `adk deploy agent_engine` (also visible via
the Agent Engine list in the Vertex AI console). `AGENT_ENGINE_LOCATION` is the `--region` you
passed to that deploy command — it's deliberately a separate variable from
`GOOGLE_CLOUD_LOCATION`, since that one picks the Gemini model endpoint (e.g. `global`) and can
be a different value.

The script builds the container from `slack_bot/Dockerfile`, stores the Slack token and signing
secret in Secret Manager, grants Cloud Run's runtime service account access to read them, and
deploys to Cloud Run with `min-instances=0`. It prints the service URL to use for the Event
Subscriptions Request URL above. Re-running it updates the existing service and secrets in place.

The service is also deployed with `--max-instances=1`, and that one is a correctness constraint:
the bot keeps its Slack-thread → Agent Engine session mapping in memory, so a second instance
wouldn't know about threads the first one has seen and would restart their conversations from
scratch. For the same reason, a thread mentioned again after the service has scaled to zero starts
a fresh session. Lifting either limitation means moving that mapping to a shared store (Firestore,
Redis).

Then in Slack: `@SRE Agent what's going on in namespace toto?`

### Local testing

```bash
uv run --group slack python -m slack_bot.app
```

Runs the Flask dev server on `:8080`. Slack needs a public URL to reach it — expose one with e.g.
`ngrok http 8080` and use that as a temporary Event Subscriptions Request URL while testing.

## Conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat: `, `fix: `, `chore: `, `docs: `, `refactor: `, `test: `). See [`CLAUDE.md`](CLAUDE.md)
for the full list of project constraints (read-only, credentials kept out of the repo, etc.).
