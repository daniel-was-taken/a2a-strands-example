#!/usr/bin/env bash
# Deploy the A2A Database Orchestrator to Cloud Run via Terraform.
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login && gcloud auth application-default login)
#   - Terraform >= 1.5 installed
#   - infra/terraform.tfvars configured (copy from terraform.tfvars.example)
#
# Usage:
#   ./deploy.sh                   # Build, push, and deploy
#   ./deploy.sh --skip-build      # Deploy without rebuilding the image

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/infra"

# ── Read config from tfvars ──────────────────────────────────────────
if [[ ! -f "${INFRA_DIR}/terraform.tfvars" ]]; then
  echo "ERROR: infra/terraform.tfvars not found. Copy from terraform.tfvars.example and fill in values."
  exit 1
fi

PROJECT_ID=$(grep 'project_id' "${INFRA_DIR}/terraform.tfvars" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
REGION=$(grep 'region' "${INFRA_DIR}/terraform.tfvars" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
SERVICE_NAME=$(grep 'service_name' "${INFRA_DIR}/terraform.tfvars" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
IMAGE_TAG=$(grep 'image_tag' "${INFRA_DIR}/terraform.tfvars" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
IMAGE_TAG="${IMAGE_TAG:-latest}"

REPO_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/a2a-orchestrator"
IMAGE="${REPO_URL}/${SERVICE_NAME}:${IMAGE_TAG}"

echo "=== A2A Orchestrator Deploy ==="
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Image:    ${IMAGE}"
echo ""

# ── Build & push ─────────────────────────────────────────────────────
if [[ "${1:-}" != "--skip-build" ]]; then
  echo ">> Configuring Docker for Artifact Registry..."
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

  echo ">> Building container image..."
  docker build -t "${IMAGE}" "${SCRIPT_DIR}"

  echo ">> Pushing image..."
  docker push "${IMAGE}"
  echo ""
fi

# ── Terraform apply ──────────────────────────────────────────────────
echo ">> Running Terraform..."
cd "${INFRA_DIR}"
terraform init -upgrade
terraform apply -auto-approve

echo ""
echo "=== Deploy complete ==="
terraform output service_url
