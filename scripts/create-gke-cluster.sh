#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
CLUSTER_NAME="${CLUSTER_NAME:-sre-agent-poc}"
ZONE="${ZONE:-europe-west1-b}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
NUM_NODES="${NUM_NODES:-1}"
DISK_SIZE_GB="${DISK_SIZE_GB:-20}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Erreur : aucun projet GCP défini (gcloud config set project <id> ou export PROJECT_ID=...)" >&2
  exit 1
fi

echo "Projet       : ${PROJECT_ID}"
echo "Cluster      : ${CLUSTER_NAME}"
echo "Zone         : ${ZONE}"
echo "Machine type : ${MACHINE_TYPE} x${NUM_NODES}, disque ${DISK_SIZE_GB}Go"

echo "Activation des APIs nécessaires..."
gcloud services enable \
  container.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  --project "${PROJECT_ID}"

echo "Création du cluster GKE..."
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

echo "Récupération des credentials kubectl..."
gcloud container clusters get-credentials "${CLUSTER_NAME}" \
  --zone "${ZONE}" \
  --project "${PROJECT_ID}"

echo "Terminé. Contexte kubectl configuré pour '${CLUSTER_NAME}'."
