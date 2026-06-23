# Infrastructure Provisioning & Private VPC Networking

This directory contains the **Terraform** configurations to provision the private networking, queueing, storage, and identity infrastructure required to host the secure task ingestion pipeline.

---

## Infrastructure Architecture Diagram

The following diagram illustrates the private networking topology and IAM security boundaries established by this Terraform configuration:

```mermaid
graph TD
    subgraph Google Cloud Platform
        subgraph Private VPC Network (task-vpc)
            Subnet["task-subnet (10.0.0.0/24) <br> Private Google Access (PGA) Enabled"]
        end
        
        subgraph Cloud Run Service Runtimes
            API["Task API <br> (Direct VPC Egress)"]
            Handler["vLLM Task Handler <br> (Direct VPC Egress)"]
        end

        subgraph IAM & Identity
            Agent["Cloud Run Service Agent <br> (service-PROJECT_NUMBER@serverless-robot-prod)"]
            Agent -->|IAM: compute.networkUser| Subnet
        end

        subgraph Storage & Queueing
            GCS["GCS Bucket <br> (gs://jkwng-model-data)"]
            Queue["Cloud Tasks Queue <br> (work-queue)"]
        end

        API -->|Direct VPC Egress| Subnet
        Handler -->|Direct VPC Egress| Subnet
        Subnet -->|Private API Calls via PGA| GCS
        API -->|Enqueue| Queue
        Queue -->|Trigger| Handler
    end
```

---

## Provisioned Resources

This module automates the creation and configuration of the following resources:

### 1. Private VPC Networking (`network.tf`)
*   **VPC Network (`task-vpc`)**: A private virtual network that isolates all backend communication.
*   **Subnetwork (`task-subnet`)**: A regional subnet in `us-central1` (`10.0.0.0/24`) with **Private Google Access (PGA)** enabled. PGA allows internal Cloud Run containers to communicate with Google Cloud APIs (like GCS) over Google's secure internal fiber backbone, bypassing the public internet entirely.
*   **IAM Subnet Binding**: Grants the Google-managed **Cloud Run Service Agent** the `roles/compute.networkUser` role on the subnetwork. This is the security prerequisite that allows Cloud Run to route traffic through Direct VPC Egress.

### 2. Services Configuration (`run.tf`)
*   Defines the base Cloud Run services (**`taskapi`** and **`taskhandler`**).
*   Enables **Direct VPC Egress** on both services, routing all outbound container traffic privately through `task-subnet`.
*   Disables CPU idle throttling (`cpu_idle = false`) on the `taskhandler` service to keep the CPU always allocated for asynchronous tasks.
*   Configures the `taskhandler` **HTTP startup probe** on `/health` (port `8090`) with a **300-second (5-minute) boot budget** ($10\text{s} \times 30\text{ checks} = 300\text{s}$ with a 2-minute initial delay) and a **15-second frequent liveness probe** to recycle frozen instances.
*   Sets scaling bounds (`maxScale = 2`, `concurrency = 4`) directly in the infrastructure state to prevent quota violations and memory OOMs.

### 3. Storage, Queueing & IAM (`gcs.tf`, `queue.tf`, `iam.tf`)
*   **GCS Bucket**: Secure bucket for image uploads and task state JSONs.
*   **Cloud Tasks Queue**: Asynchronous queue for managing task ingestion retries and rate-limiting.
*   **Service Accounts**: Dedicated identities (`taskapi` and `taskhandler` service accounts) with least-privilege IAM roles for GCS read/write, Pub/Sub publishing, and Cloud Tasks invocation.

---

## How to Provision

### 1. Configure Variables
Open `terraform.tfvars` (or create one) and set your target deployment variables:
```hcl
billing_account_id = "your-billing-account-id"
service_project_id = "your-gcp-project-id"
region             = "us-central1"
```

### 2. Apply the Configuration
Execute the following commands from the `terraform/` directory:
```bash
# Initialize the Terraform state and download providers
terraform init

# Review the planned infrastructure changes
terraform plan

# Apply the configuration and provision resources
terraform apply
```

### 3. Outputs
On successful completion, Terraform will output the created resource details, including:
*   `gcs_bucket_name`
*   `cloud_tasks_queue_name`
*   `task_handler_service_account`
*   `task_api_service_account`
