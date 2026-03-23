variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "a2a-orchestrator"
  format        = "DOCKER"
  description   = "Container images for A2A Database Orchestrator"
}

output "repository_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}
