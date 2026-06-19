# Cloud Run Deployment Guide

This guide explains how to deploy the **Task API** (Node.js/TypeScript) and the **Task Handler** (Go) to separate Google Cloud Run services.

We provide a unified deployment script `deploy.sh` at the root of the repository that orchestrates the build and deployment process.

---

## Prerequisites

Before running the deployment script, ensure you have:

1.  **Google Cloud SDK (`gcloud` CLI)** installed and authenticated:
    ```bash
    gcloud auth login
    gcloud auth application-default login
    ```
2.  **A Google Cloud Project** with the following APIs enabled:
    -   Artifact Registry (`artifactregistry.googleapis.com`)
    -   Cloud Build (`cloudbuild.googleapis.com`)
    -   Cloud Run (`run.googleapis.com`)
    -   Cloud Tasks (`cloudtasks.googleapis.com`)
    -   Pub/Sub (`pubsub.googleapis.com`)
    -   Cloud Storage (`storage.googleapis.com`)
    -   IAM (`iam.googleapis.com`)

3.  **Foundation Infrastructure**: The services require a GCS Bucket, a Cloud Tasks Queue, and multiple Service Accounts with specific IAM permissions to function correctly. 
    -   You can provision these foundations automatically using the provided Terraform configuration in the `terraform/` directory.

---

## Deployment Steps

### Step 1: Provision Infrastructure (Recommended)

Navigate to the `terraform/` directory and apply the configuration to set up the GCS buckets, service accounts, and permissions:

```bash
cd terraform
terraform init
terraform apply
cd ..
```

This will output the created resource names and URLs. Specifically, look for:
-   **GCS Bucket Name** (e.g., `jkwng-data-xxxxx`)
-   **Cloud Tasks Queue Name** (e.g., `work-queue-xxxxx`)

### Step 2: Configure the Deployment Script

Open [deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/deploy.sh) and update the configuration variables at the top of the file to match your GCP project and the resources created in Step 1:

```bash
# ==============================================================================
# 1. CONFIGURATION VARIABLES
# ==============================================================================
PROJECT_ID="your-gcp-project-id"       # <-- Your GCP Project ID
REGION="us-central1"                   # <-- Target region
AR_REPO_NAME="tasks-repo"              # <-- Artifact Registry repository name

# Service Accounts (Use the ones created by Terraform or create them manually)
TASKAPI_SA="taskapi@${PROJECT_ID}.iam.gserviceaccount.com"
TASKHANDLER_SA="taskhandler@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_QUEUE_SA="cloud-tasks@${PROJECT_ID}.iam.gserviceaccount.com"
STORAGE_SA="storage@${PROJECT_ID}.iam.gserviceaccount.com"

# Task API Environment Variables
BUCKET_NAME="your-gcs-bucket-name"     # <-- GCS Bucket Name (from Step 1)
BUCKET_PREFIX="input"
QUEUE_NAME="work-queue"                # <-- Cloud Tasks Queue Name (from Step 1)

# Task Handler Environment Variables
INIT_SLEEP_SEC=5
HANDLE_INPUT_SLEEP_SEC=2
# ==============================================================================
```

### Step 3: Run the Deployment Script

Run the script from the root of the repository:

```bash
./deploy.sh
```

### What `deploy.sh` Does:
1.  **Verifies Prerequisites**: Confirms `gcloud` is installed, authenticated, and configured for the correct project.
2.  **Creates Artifact Registry Repo**: Creates a Docker repository named `tasks-repo` (if it does not already exist) to host the images.
3.  **Builds & Deploys Task Handler**:
    -   Submits the Go code in `taskhandler/` to Google Cloud Build.
    -   Packages the Go binary into a minimal scratch/distroless container.
    -   Deploys it to Cloud Run as a private service (`--no-allow-unauthenticated`) running on port `8090`.
    -   Captures the deployed service URL.
4.  **Builds & Deploys Task API**:
    -   Submits the TypeScript code in `taskapi/` to Google Cloud Build.
    -   Compiles the TypeScript and runs the Jest unit test suite inside the build container to ensure code health before deployment.
    -   Deploys it to Cloud Run as a public service (`--allow-unauthenticated`) running on port `8000`.
    -   Passes all required environment variables including the captured `TASK_HANDLER_URL`.

---

## Post-Deployment Validation

Once the script completes, it will print the service URLs:
-   **Task API URL**: The public endpoint for the web dashboard.
-   **Task Handler URL**: The private endpoint invoked via Cloud Tasks.

1.  **Open the Web Dashboard**:
    Copy the **Task API URL** and open it in your browser. You should see the file upload dashboard.
2.  **Upload a File**:
    Drag and drop an image (or use the upload form) in the dashboard.
3.  **Verify Flow**:
    -   The file is uploaded to GCS.
    -   GCS triggers a Pub/Sub notification to Task API.
    -   Task API enqueues a task in Cloud Tasks.
    -   Cloud Tasks invokes the Task Handler.
    -   Task Handler processes the image (simulated sleep) and writes a JSON status file back to GCS.
    -   The dashboard will automatically update to show the task transitioning from `PENDING` -> `RUNNING` -> `COMPLETED`.
