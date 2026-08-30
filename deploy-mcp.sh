#!/usr/bin/env bash
# Deploy the teleping Telegram MCP server to Cloud Run.
#
# Usage:
#   PROJECT_ID=my-project ./deploy-mcp.sh
#
# Optional env vars:
#   REGION        (default us-central1)
#   SERVICE_NAME  (default teleping)
#   BUCKET        GCS bucket for the bot registry (default <project>-teleping-bots;
#                 created if missing)
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID to your GCP project id}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-teleping}"
BUCKET="${BUCKET:-${PROJECT_ID}-teleping-bots}"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Unguessable path segment protecting the endpoint. Reuse the service's
# existing secret on redeploys so the connector URL stays stable.
EXISTING_SECRET="$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format 'value(spec.template.spec.containers[0].env.filter("name:MCP_PATH_SECRET").extract("value").flatten())' \
  2>/dev/null || true)"
MCP_PATH_SECRET="${EXISTING_SECRET:-$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)}"

# Registry bucket (idempotent).
gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1 || \
  gsutil mb -p "${PROJECT_ID}" -l "${REGION}" "gs://${BUCKET}"

gcloud builds submit --project "${PROJECT_ID}" --tag "${IMAGE}" .

gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --set-env-vars "MCP_PATH_SECRET=${MCP_PATH_SECRET},BOTS_GCS_BUCKET=${BUCKET}"

# Give the service's runtime account access to the registry bucket.
SA="$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format 'value(spec.template.spec.serviceAccountName)')"
gsutil iam ch "serviceAccount:${SA}:roles/storage.objectAdmin" "gs://${BUCKET}"

URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')"

# The server needs its own public URL to build /gmail app-redirect button
# links. Set it after the first deploy (idempotent on redeploys).
gcloud run services update "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --update-env-vars "SERVICE_URL=${URL}" --quiet

echo
echo "MCP endpoint (add as a claude.ai custom connector — treat as secret):"
echo "  ${URL}/${MCP_PATH_SECRET}/mcp"
