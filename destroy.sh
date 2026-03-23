#!/usr/bin/env bash
# Tear down all Cloud Run + Artifact Registry resources created by deploy.sh.
#
# Usage:
#   ./destroy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/infra"

if [[ ! -f "${INFRA_DIR}/terraform.tfvars" ]]; then
  echo "ERROR: infra/terraform.tfvars not found."
  exit 1
fi

echo "=== A2A Orchestrator Destroy ==="
echo ""
echo "This will permanently delete all deployed infrastructure."
read -rp "Continue? (y/N) " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

cd "${INFRA_DIR}"
terraform destroy -auto-approve

echo ""
echo "=== Destroy complete ==="
