# ==============================================================================
# Identity-Aware Proxy (IAP) Access Control Configuration
# ==============================================================================

# Data source to programmatically retrieve the project number for IAM bindings
data "google_project" "project" {
  project_id = module.service_project.project_id
}

# 1. Grant the IAP Service Agent permission to invoke the private Cloud Run service
# This is a security prerequisite for IAP to route authenticated traffic.
resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  project  = google_cloud_run_v2_service.taskapi.project
  location = google_cloud_run_v2_service.taskapi.location
  name     = google_cloud_run_v2_service.taskapi.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-iap.iam.gserviceaccount.com"
}

# 2. Grant access to the specified users to access the IAP-secured Task API
# This assigns the "IAP-secured Web App User" role specifically for this service resource.
resource "google_iap_web_cloud_run_service_iam_member" "taskapi_iap_user" {
  for_each = toset(var.iap_accessor_members)

  project                = google_cloud_run_v2_service.taskapi.project
  location               = google_cloud_run_v2_service.taskapi.location
  cloud_run_service_name = google_cloud_run_v2_service.taskapi.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}


