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
  project             = module.service_project.project_id
  name                = "taskapi"
  location            = var.region
  deletion_protection = false

  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
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
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
      }
      egress = "ALL_TRAFFIC"
    }
    service_account = google_service_account.taskapi.email
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
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
  project             = module.service_project.project_id
  name                = "taskhandler"
  location            = var.region
  deletion_protection = false

  template {
    max_instance_request_concurrency = 4

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      ports { 
        container_port = 8090
      }
      resources {
        limits = {
          cpu    = "8"
          memory = "32Gi"
        }
        cpu_idle = false
      }
      startup_probe {
        initial_delay_seconds = 120
        timeout_seconds       = 10
        period_seconds        = 10
        failure_threshold     = 60
        http_get {
          path = "/health"
        }
      }
      liveness_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 15
        failure_threshold     = 3
        http_get {
          path = "/health"
        }
      }
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
      }
      egress = "ALL_TRAFFIC"
    }
    service_account = google_service_account.taskhandler_sa.email
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }
}