# Cloud Run Deployment Guide

This guide explains how to deploy the **Task API** (Node.js/TypeScript) and the **Task Handler** (Go) to separate Google Cloud Run services.

Instead of a single monolithic script, we provide **two separate, self-contained deployment scripts** located in their respective directories. This allows you to manage, build, and deploy each service independently.

---

## Prerequisites

Before running the deployment scripts, ensure you have:

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

---

### Step 2: Deploy the Task Handler First

Because the Task API depends on the URL of the Task Handler, **you must deploy the Task Handler first**.

1.  Open [taskhandler/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskhandler/deploy.sh) and update the configuration variables at the top:
    ```bash
    PROJECT_ID="your-gcp-project-id"       # <-- Your GCP Project ID
    REGION="us-central1"                   # <-- Target region
    AR_REPO_NAME="tasks-repo"              # <-- Artifact Registry repository name
    ```
2.  Run the deployment script from the `taskhandler/` directory:
    ```bash
    cd taskhandler
    ./deploy.sh
    cd ..
    ```

**What it does:**
-   Creates the Artifact Registry repository if missing.
-   Submits Go source code to Google Cloud Build.
-   Packages it into a minimal distroless image.
-   Deploys to Cloud Run as a private service (`--no-allow-unauthenticated`) running on port `8090`.
-   Prints the newly created private Service URL.

---

### Step 3: Deploy the Task API

Once the Task Handler is successfully deployed, you can deploy the Task API. The deployment script will automatically query Cloud Run to detect the Task Handler's URL if it is not manually specified.

1.  Open [taskapi/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskapi/deploy.sh) and update the configuration variables at the top:
    ```bash
    PROJECT_ID="your-gcp-project-id"       # <-- Your GCP Project ID
    REGION="us-central1"                   # <-- Target region
    AR_REPO_NAME="tasks-repo"              # <-- Artifact Registry repository name

    # Task API Environment Variables
    BUCKET_NAME="your-gcs-bucket-name"     # <-- GCS Bucket Name (from Step 1)
    BUCKET_PREFIX="input"
    QUEUE_NAME="work-queue"                # <-- Cloud Tasks Queue Name (from Step 1)
    
    # Task Handler Integration
    # Leave TASK_HANDLER_URL blank to automatically detect it!
    TASK_HANDLER_URL="" 
    TASKHANDLER_SERVICE_NAME="taskhandler" # <-- Name of the deployed handler service
    ```
2.  Run the deployment script from the `taskapi/` directory:
    ```bash
    cd taskapi
    ./deploy.sh
    cd ..
    ```

**What it does:**
-   Queries Cloud Run to resolve the URL for `taskhandler` in your project and region.
-   Submits TypeScript source code to Google Cloud Build.
-   Runs TypeScript compilation and Jest tests inside the build container to verify code health before packaging.
-   Deploys to Cloud Run as a public service (`--allow-unauthenticated`) running on port `8000`.
-   Injects all correct environment variables, including the detected `TASK_HANDLER_URL`.

---

## Post-Deployment Validation

Once both scripts complete, you will see their endpoints:
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
