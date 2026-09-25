#!/usr/bin/env bash
set -euo pipefail

# Deploys the Slack bot (slack_bot/) to Cloud Run as an HTTP service that
# receives Slack's Events API callbacks. min-instances=0 means no traffic ->
# no running container -> no compute cost between mentions (see CLAUDE.md /
# README "Slack interface" for the architecture).
#
# Prerequisites:
#   - The agent already deployed via `adk deploy agent_engine` (README).
#   - A Slack app with Event Subscriptions (not Socket Mode) — see README.
#   - `gcloud auth login` done locally, with permission to deploy Cloud Run
#     services and manage secrets on the target project.
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

# Cloud Run's default runtime service account needs explicit access to read
# these secrets — it has no Secret Manager permissions by default.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

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
