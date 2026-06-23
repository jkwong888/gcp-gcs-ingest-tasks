# Data source to fetch project metadata (specifically the project number)
data "google_project" "service_project" {
  project_id = module.service_project.project_id
}

# Create the private VPC Network
resource "google_compute_network" "vpc" {
  project                 = module.service_project.project_id
  name                    = "task-vpc"
  auto_create_subnetworks = false
}

# Create the Subnetwork in the deployment region
resource "google_compute_subnetwork" "subnet" {
  project                  = module.service_project.project_id
  name                     = "task-subnet"
  ip_cidr_range            = "10.0.0.0/24"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}

# Grant the Cloud Run Service Agent the compute.networkUser role on the subnet.
# This is a mandatory IAM requirement for Direct VPC Egress to route traffic.
resource "google_compute_subnetwork_iam_member" "cloudrun_network_user" {
  project    = module.service_project.project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.subnet.name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:service-${data.google_project.service_project.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
