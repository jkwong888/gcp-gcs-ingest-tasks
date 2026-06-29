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
  
  # Enable Identity-Aware Proxy (IAP) directly on the service
  iap_enabled         = true

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
    max_instance_request_concurrency = 8

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      ports { 
        container_port = 8090
      }
      resources {
        limits = {
          cpu    = "1"      # Downsized to 1 vCPU
          memory = "1Gi"    # Downsized to 1Gi
        }
        # Removed cpu_idle = false to enable CPU throttling (cost-effective when idle)
      }
      startup_probe {
        initial_delay_seconds = 10   # Reduced from 120 (CPU starts fast)
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3    # Reduced from 60
        http_get {
          path = "/health"
        }
      }
      liveness_probe {
        initial_delay_seconds = 5    # Set to 5 (from 0) for stability
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

# ==============================================================================
# Ingestion Task API (Split component for Pub/Sub push notifications)
# ==============================================================================

# 1. Service Account for Ingestion Task API
resource "google_service_account" "taskapi_ingest" {
  project    = module.service_project.project_id
  account_id = "taskapi-ingest"
}

# 2. Ingestion Task API Service (Secured by standard Cloud Run IAM, no IAP)
resource "google_cloud_run_v2_service" "taskapi_ingest" {
  project             = module.service_project.project_id
  name                = "taskapi-ingest"
  location            = var.region
  deletion_protection = false

  template {
    containers {
      # Initial deployment uses standard hello image; deploy.sh will push the real container
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      ports {
        container_port = 8000
      }
      
      env {
        name  = "BUCKET_NAME"
        value = google_storage_bucket.data.name
      }

      env {
        name  = "QUEUE_NAME"
        value = google_cloud_tasks_queue.work.name
      }

      env {
        name  = "PROJECT_ID"
        value = module.service_project.project_id
      }

      env {
        name  = "REGION"
        value = var.region
      }

      env {
        name  = "TASK_HANDLER_URL"
        value = google_cloud_run_v2_service.taskhandler.uri
      }

      env {
        name  = "TASKS_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.tasks_sa.email
      }
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
      }
      egress = "ALL_TRAFFIC"
    }
    
    service_account = google_service_account.taskapi_ingest.email
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }
}

# 3. Grant Pub/Sub (storage SA) permission to invoke the Ingestion service directly via IAM
resource "google_cloud_run_v2_service_iam_member" "pubsub_ingest_invoker" {
  project  = google_cloud_run_v2_service.taskapi_ingest.project
  location = google_cloud_run_v2_service.taskapi_ingest.location
  name     = google_cloud_run_v2_service.taskapi_ingest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.storage.email}"
}