data "google_project" "registry_project" {
  project_id = var.registry_project_id
}

# Allow the service project's Cloud Run service agent to pull images from Artifact Registry
# Depends on module.service_project to ensure Cloud Run API is enabled and the service agent is created.
resource "google_project_iam_member" "registry_reader" {
  project    = data.google_project.registry_project.project_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${module.service_project.number}@serverless-robot-prod.iam.gserviceaccount.com"
  depends_on = [module.service_project]
}

# Allow the service project's Compute Engine default SA (used by Cloud Build) to push images to Artifact Registry
# Depends on module.service_project to ensure Compute Engine API is enabled and the default SA is created.
resource "google_project_iam_member" "registry_writer" {
  project    = data.google_project.registry_project.project_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${module.service_project.number}-compute@developer.gserviceaccount.com"
  depends_on = [module.service_project]
}

# Grant Cloud Build builder role to the Compute Engine default SA in the service project
# This allows it to access the local Cloud Build source GCS bucket.
# Depends on module.service_project to ensure Compute Engine API is enabled and the default SA is created.
resource "google_project_iam_member" "compute_builder" {
  project    = module.service_project.project_id
  role       = "roles/cloudbuild.builds.builder"
  member     = "serviceAccount:${module.service_project.number}-compute@developer.gserviceaccount.com"
  depends_on = [module.service_project]
}