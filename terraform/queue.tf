resource "google_cloud_tasks_queue" "work" {
  project   = module.service_project.project_id
  name      = "work-queue-${random_id.random_suffix.hex}"
  location  = "us-central1"

  retry_config {
    max_attempts = 100
    max_retry_duration = "600s"
    max_backoff = "5s"
    min_backoff = "0.100s"
    max_doublings = 16
  }
}


resource "google_cloud_tasks_queue_iam_member" "taskapi_enqueuer" {
  project   = google_cloud_tasks_queue.work.project
  name      = google_cloud_tasks_queue.work.name
  location  = google_cloud_tasks_queue.work.location
  role = "roles/cloudtasks.enqueuer"
  member = "serviceAccount:${google_service_account.taskapi.email}"

}

// allow taskapi to create tokens as itself (for signedUrl generation)
resource "google_service_account_iam_member" "taskapi_token_creator" {
  service_account_id = google_service_account.taskapi.id
  role = "roles/iam.serviceAccountTokenCreator"
  member = "serviceAccount:${google_service_account.taskapi.email}"
}

// SA for task queue (invokes task handler)
resource "google_service_account" "tasks_sa" {
  project   = module.service_project.project_id
  account_id = "cloud-tasks"
}

// allow taskapi to create tokens as tasks queue
resource "google_service_account_iam_member" "taskapi_tasks_sa_user" {
  service_account_id = google_service_account.tasks_sa.id
  role = "roles/iam.serviceAccountUser"
  member = "serviceAccount:${google_service_account.taskapi.email}"
}

