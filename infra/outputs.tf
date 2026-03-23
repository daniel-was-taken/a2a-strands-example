output "service_url" {
  description = "Cloud Run service URL"
  value       = module.cloudrun.service_url
}

output "repository_url" {
  description = "Artifact Registry repository URL"
  value       = module.artifact_registry.repository_url
}
