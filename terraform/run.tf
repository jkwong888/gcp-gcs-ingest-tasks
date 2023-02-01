data "google_iam_policy" "noauth" {
  binding {
    role = "roles/run.invoker"
    members = [
      "allUsers",
    ]
  }
}

resource "google_cloud_run_service_iam_policy" "noauth" {
  location    = var.region
  project     = module.service_project.project_id
  service     = google_cloud_run_v2_service.taskapi.name

  policy_data = data.google_iam_policy.noauth.policy_data
}

// Cloud Run SA for task api (adds tasks to queue)
resource "google_service_account" "taskapi" {
  project   = module.service_project.project_id
  account_id = "taskapi"
}


resource "google_cloud_run_v2_service" "taskapi" {
  project  = module.service_project.project_id
  name     = "taskapi-${random_id.random_suffix.hex}"
  location = var.region

  template {
    containers {
      image = var.taskapi_image
      ports { 
        container_port = 8000
      }
      env {
        name = "BUCKET_NAME"
        value = google_storage_bucket.data.name
      }

      env {
        name = "QUEUE_NAME"
        value = google_cloud_tasks_queue.work.name
      }

      env {
        name = "PROJECT_ID"
        value = module.service_project.project_id
      }

      env {
        name = "REGION"
        value = var.region
      }

      env {
        name = "TASK_HANDLER_URL"
        value = google_cloud_run_v2_service.taskhandler.uri
      }

      env {
        name = "TASKS_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.tasks_sa.email
      }

      env {
        name = "STORAGE_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.storage.email
      }


    }
    service_account = google_service_account.taskapi.email
  }

}

// Cloud Run SA for task handler (handles tasks)
resource "google_service_account" "taskhandler_sa" {
  project   = module.service_project.project_id
  account_id = "taskhandler"
}

resource "google_cloud_run_v2_service_iam_member" "tasks_invoker" {
  project   = google_cloud_run_v2_service.taskhandler.project
  location  = google_cloud_run_v2_service.taskhandler.location
  name  = google_cloud_run_v2_service.taskhandler.name
  role = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.tasks_sa.email}"

}

resource "google_cloud_run_v2_service" "taskhandler" {
  project  = module.service_project.project_id
  name     = "taskhandler-${random_id.random_suffix.hex}"
  location = var.region

  template {
    containers {
      image = var.taskhandler_image
      ports { 
        container_port = 8090
      }
    }
    service_account = google_service_account.taskhandler_sa.email
  }

}