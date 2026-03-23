terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "artifact_registry" {
  source     = "./modules/artifact-registry"
  project_id = var.project_id
  region     = var.region
}

module "cloudrun" {
  source       = "./modules/cloudrun-runtime"
  project_id   = var.project_id
  region       = var.region
  service_name = var.service_name
  image        = "${module.artifact_registry.repository_url}/${var.service_name}:${var.image_tag}"
  env_vars     = var.env_vars
  secrets      = var.secrets

  depends_on = [module.artifact_registry]
}
