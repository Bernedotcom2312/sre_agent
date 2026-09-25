#!/usr/bin/env bash
set -euo pipefail

# Deploys the Slack bot (slack_bot/) to Cloud Run as an HTTP service that
# receives Slack's Events API callbacks. min-instances=0 means no traffic ->
# no running container -> no compute cost between mentions (see CLAUDE.md /
# README "Slack interface" for the architecture).
#
# The service runs as its own least-privilege service account (see
# RUNTIME_SA below), not as the project's default Compute account.
#
# Prerequisites:
#   - The agent already deployed via `adk deploy agent_engine` (README).
#   - A Slack app with Event Subscriptions (not Socket Mode) — see README.
#   - `gcloud auth login` done locally, with permission to deploy Cloud Run
#     services, manage secrets, and create service accounts / grant roles on
#     the target project (Cloud Run also requires iam.serviceAccounts.actAs
#     on the runtime account, which Owner/Editor already covers).
#
# Usage:
#   PROJECT_ID=<gcp-project> \
#   AGENT_ENGINE_LOCATION=<region> \
#   AGENT_ENGINE_RESOURCE_NAME=projects/.../reasoningEngines/<id> \
#   SLACK_BOT_TOKEN=xoxb-... \
#   SLACK_SIGNING_SECRET=... \
#   ./scripts/deploy-slack-bot-cloud-run.sh

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-sre-agent-slack-bot}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-sre-agent-slack-bot}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: no GCP project set (gcloud config set project <id> or export PROJECT_ID=...)" >&2
  exit 1
fi

: "${AGENT_ENGINE_LOCATION:?Set AGENT_ENGINE_LOCATION (the --region passed to adk deploy agent_engine)}"
: "${AGENT_ENGINE_RESOURCE_NAME:?Set AGENT_ENGINE_RESOURCE_NAME (printed by adk deploy agent_engine)}"
: "${SLACK_BOT_TOKEN:?Set SLACK_BOT_TOKEN (xoxb-..., from the Slack app's OAuth & Permissions page)}"
: "${SLACK_SIGNING_SECRET:?Set SLACK_SIGNING_SECRET (from the Slack app's Basic Information page)}"

echo "Project      : ${PROJECT_ID}"
echo "Region       : ${REGION}"
echo "Service      : ${SERVICE_NAME}"

echo "Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  --project "${PROJECT_ID}"

create_or_update_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --project "${PROJECT_ID}" --data-file=-
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --project "${PROJECT_ID}" --data-file=- --replication-policy=automatic
  fi
}

echo "Storing Slack credentials in Secret Manager..."
create_or_update_secret slack-bot-token "${SLACK_BOT_TOKEN}"
create_or_update_secret slack-signing-secret "${SLACK_SIGNING_SECRET}"

# Deliberately NOT Cloud Run's default runtime account
# (<project-number>-compute@developer.gserviceaccount.com): that one carries
# the Editor role on the whole project, so the bot — which only needs to
# query the agent and read two secrets — could delete a GKE workload. The
# agent's read-only guarantee (CLAUDE.md) is worth little if the identity
# hosting its front end can write anything, so give the service its own
# account and grant it just those two capabilities.
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "${RUNTIME_SA}" --project "${PROJECT_ID}" >/dev/null 2>&1
then
  echo "Runtime service account ${RUNTIME_SA} already exists."
else
  echo "Creating runtime service account ${RUNTIME_SA}..."
  gcloud iam service-accounts create "${RUNTIME_SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name "SRE Agent Slack bot (Cloud Run runtime)"
fi

grant_secret_access() {
  gcloud secrets add-iam-policy-binding "$1" \
    --project "${PROJECT_ID}" \
    --member "serviceAccount:${RUNTIME_SA}" \
    --role roles/secretmanager.secretAccessor \
    >/dev/null
}

echo "Granting ${RUNTIME_SA} access to the secrets..."
grant_secret_access slack-bot-token
grant_secret_access slack-signing-secret

# Needed to create a session on the deployed agent and stream a query to it.
# aiplatform.user is the narrowest predefined role that covers querying a
# reasoning engine; it grants nothing outside Vertex AI.
echo "Granting ${RUNTIME_SA} permission to query Agent Engine..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SA}" \
  --role roles/aiplatform.user \
  --condition=None \
  >/dev/null

# max-instances=1 is a correctness constraint, not a cost one: the bot keeps
# its Slack-thread -> Agent Engine session mapping in memory (see
# AgentSessions in slack_bot/app.py), so a second instance would restart some
# threads' conversations at random. One instance with 8 threads is plenty for
# a chat front end; lifting this means moving that mapping to a shared store.
echo "Deploying to Cloud Run (scale-to-zero: min-instances=0)..."
gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source slack_bot \
  --service-account "${RUNTIME_SA}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=1 \
  --cpu=1 \
  --memory=512Mi \
  --timeout=300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AGENT_ENGINE_LOCATION=${AGENT_ENGINE_LOCATION},AGENT_ENGINE_RESOURCE_NAME=${AGENT_ENGINE_RESOURCE_NAME}" \
  --set-secrets "SLACK_BOT_TOKEN=slack-bot-token:latest,SLACK_SIGNING_SECRET=slack-signing-secret:latest"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" --format='value(status.url)')"

echo
echo "Deployed: ${SERVICE_URL}"
echo "Set this as the Slack app's Event Subscriptions Request URL:"
echo "  ${SERVICE_URL}/slack/events"
