resource "google_storage_bucket" "data" {
  project       = module.service_project.project_id
  name          = "jkwng-data-${random_id.random_suffix.hex}"
  location      = var.region
  force_destroy = true

  #public_access_prevention = "enforced"
  uniform_bucket_level_access = true
}

// topic for object change notifications
resource "google_pubsub_topic" "file_uploads" {
  project   = module.service_project.project_id
  name      = "uploaded_file_notification"
}

// create a pubsub message when objects in upload/ change in the bucket
resource "google_storage_notification" "notification" {
  bucket         = google_storage_bucket.data.name
  payload_format = "JSON_API_V1"
  topic          = google_pubsub_topic.file_uploads.id
  event_types    = ["OBJECT_FINALIZE", "OBJECT_METADATA_UPDATE"]
  object_name_prefix = "upload/"
  depends_on = [google_pubsub_topic_iam_binding.binding]
}

// Enable notifications by giving the correct IAM permission to the unique service account.
data "google_storage_project_service_account" "gcs_account" {
  project   = module.service_project.project_id
}

// allow GCS to write to the notification topic
resource "google_pubsub_topic_iam_binding" "binding" {
  topic   = google_pubsub_topic.file_uploads.id
  role    = "roles/pubsub.publisher"
  members = ["serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"]
}

// allow taskapi to create objects on gcs
resource "google_storage_bucket_iam_member" "taskapi_write_gcs" {
  bucket = google_storage_bucket.data.name
  role = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.taskapi.email}"
}

// SA for generating signed urls 
resource "google_service_account" "storage" {
  project   = module.service_project.project_id
  account_id = "storage"
}

// allow pubsub to create a token in order to call the taskapi when notifying of file uploads
resource "google_service_account_iam_member" "pubsub_storage_token_creator" {
  service_account_id = google_service_account.storage.id
  role = "roles/iam.serviceAccountTokenCreator"
  member = "serviceAccount:service-${module.service_project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

// allow the task handler to read/write to GCS on the bucket
resource "google_storage_bucket_iam_member" "taskhandler_object_admin" {
  bucket = google_storage_bucket.data.name
  role = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.taskhandler_sa.email}"
}

resource "google_pubsub_subscription" "gcs_notification" {
  project   = module.service_project.project_id
  name  = "gcs_notification"
  topic = google_pubsub_topic.file_uploads.name

  ack_deadline_seconds = 20

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.taskapi.uri}/uploadNotification"
    oidc_token {
      service_account_email = google_service_account.storage.email
    }
  }
}