variable "billing_account_id" {
  default = ""
}

variable "organization_id" {
  default = "" 
}

variable "parent_folder_id" {
  default = "" 
}

variable "service_project_id" {
  description = "The ID of the service project which hosts the project resources e.g. dev-55427"
}

variable "registry_project_id" {
}

variable "shared_vpc_host_project_id" {
  description = "The ID of the host project which hosts the shared VPC e.g. shared-vpc-host-project-55427"
}

variable "shared_vpc_network" {
  description = "The ID of the shared VPC e.g. shared-network"
}

variable "service_project_apis_to_enable" {
  type = list(string)
  default = [
    "compute.googleapis.com",
  ]
}

variable "region" {
  default = "us-central1"
}

variable "subnets" {
  type = list(object({
    name=string,
    region=string,
    primary_range=string,
    secondary_range=map(any)
  }))
  default = []
}


variable "taskapi_image" {}
variable "taskhandler_image" {}
