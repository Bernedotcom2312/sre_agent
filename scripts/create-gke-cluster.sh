#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
CLUSTER_NAME="${CLUSTER_NAME:-sre-agent-poc}"
ZONE="${ZONE:-europe-west1-b}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
NUM_NODES="${NUM_NODES:-1}"
DISK_SIZE_GB="${DISK_SIZE_GB:-20}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: no GCP project set (gcloud config set project <id> or export PROJECT_ID=...)" >&2
  exit 1
fi

echo "Project      : ${PROJECT_ID}"
echo "Cluster      : ${CLUSTER_NAME}"
echo "Zone         : ${ZONE}"
echo "Machine type : ${MACHINE_TYPE} x${NUM_NODES}, disk ${DISK_SIZE_GB}GB"

echo "Enabling required APIs..."
gcloud services enable \
  container.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  --project "${PROJECT_ID}"

echo "Creating the GKE cluster..."
gcloud container clusters create "${CLUSTER_NAME}" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}" \
  --machine-type "${MACHINE_TYPE}" \
  --num-nodes "${NUM_NODES}" \
  --disk-size "${DISK_SIZE_GB}" \
  --disk-type pd-standard \
  --logging=SYSTEM,WORKLOAD \
  --monitoring=SYSTEM,WORKLOAD \
  --no-enable-ip-alias \
  --release-channel regular

echo "Fetching kubectl credentials..."
gcloud container clusters get-credentials "${CLUSTER_NAME}" \
  --zone "${ZONE}" \
  --project "${PROJECT_ID}"

echo "Done. kubectl context configured for '${CLUSTER_NAME}'."
