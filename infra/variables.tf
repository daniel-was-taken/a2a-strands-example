variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "a2a-orchestrator"
}

variable "image_tag" {
  description = "Container image tag"
  type        = string
  default     = "latest"
}

variable "env_vars" {
  description = "Environment variables for the Cloud Run service"
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secret Manager secret IDs to mount as env vars (key = env var name, value = secret ID)"
  type        = map(string)
  default     = {}
}
