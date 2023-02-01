output "task_api_url" {
    value = google_cloud_run_v2_service.taskapi.uri
}
output "task_handler_url" {
    value = google_cloud_run_v2_service.taskhandler.uri
}