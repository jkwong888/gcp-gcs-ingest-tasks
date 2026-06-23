# Cloud Run Services Deployment Guide

This guide explains how to build and deploy the **Task API** (Node.js/TypeScript) and the GPU-accelerated **vLLM Task Handler** (Python) application services to Google Cloud Run.

---

## Step 1: Provision Infrastructure Prerequisite

Before deploying the application code, you must provision the private VPC network, regional subnets, GCS buckets, queues, and service accounts.

Detailed instructions, network architecture diagrams, and IAM configurations are located in the **[`terraform/` directory](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/terraform/README.md)**. 

To provision the infrastructure, run from the repository root:
```bash
cd terraform
terraform init
terraform apply
cd ..
```
*Note the output GCS bucket name (e.g., `jkwng-data-xxxxx`) and queue name (e.g., `work-queue-xxxxx`) to use in the steps below.*

---

## Step 2: Deploy the vLLM Task Handler

Because the Task API depends on the URL of the Task Handler, **you must deploy the Task Handler first**.

1.  Open [taskhandler_vllm/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskhandler_vllm/deploy.sh) and configure the deployment variables at the top of the script:
    ```bash
    PROJECT_ID="your-gcp-project-id"           # <-- Your GCP Project ID
    REGION="us-central1"                       # <-- Target region (must support L4 GPUs, e.g., us-central1)
    REGISTRY_PROJECT_ID="jkwng-images"         # <-- GCP Project containing the GCR registry
    MODEL_PATH="gs://jkwng-model-data/models/google/gemma-4-12B-it-qat-w4a16-ct" # <-- GCS model weights path
    ```
2.  Run the deployment script from the `taskhandler_vllm/` directory:
    ```bash
    cd taskhandler_vllm
    ./deploy.sh
    ```
3.  **Fast Iterations (Skip Rebuilds)**: To deploy local Python code changes instantly (~5 seconds) without compiling a new Docker image via Cloud Build, run:
    ```bash
    ./deploy.sh --skip-build
    ```

#### Deployed Configuration Summary:
*   **Resources**: 1 NVIDIA L4 GPU, 8 vCPUs, and 32Gi Memory (always-allocated CPU via `--no-cpu-throttling`).
*   **Direct VPC Egress**: Outbound traffic is routed privately through `task-subnet` using Google's Private Google Access (PGA) to stream weights from GCS.
*   **Startup Speed (~32s)**: Streams weights in parallel (32 threads) and bypasses the 80-second JIT compilation by enabling Eager Mode (`enforce_eager=True`).
*   **Probes**: 12-minute startup probe budget (2-minute initial delay + 10-second checks up to 60 times) and 15-second frequent liveness checks on the `/health` endpoint.
*   **Autoscaling Caps**: Capped at `maxScale = 2` to comply with regional L4 GPU quotas, and `concurrency = 4` to prevent VRAM OOMs.

---

## Step 3: Deploy the Task API

Once the Task Handler is deployed, deploy the Task API. The script will automatically query Cloud Run to resolve the Task Handler's URL.

1.  Open [taskapi/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskapi/deploy.sh) and configure the variables at the top of the script:
    ```bash
    PROJECT_ID="your-gcp-project-id"           # <-- Your GCP Project ID
    REGION="us-central1"                       # <-- Target region
    REGISTRY_PROJECT_ID="jkwng-images"         # <-- GCP Project containing the GCR registry
    BUCKET_NAME="your-gcs-bucket-name"         # <-- GCS Bucket Name (from Step 1)
    QUEUE_NAME="work-queue"                    # <-- Cloud Tasks Queue Name (from Step 1)
    TASKHANDLER_SERVICE_NAME="taskhandler"     # <-- Name of your deployed handler service
    ```
2.  Run the deployment script from the `taskapi/` directory:
    ```bash
    cd taskapi
    ./deploy.sh
    cd ..
    ```

---

## Post-Deployment Validation

1.  **Open the Web Dashboard**: Copy the public **Task API URL** from the script output and open it in a browser.
2.  **Upload an Image**: Drag and drop an image onto the upload form.
3.  **Verify the Flow**:
    *   The file is uploaded to GCS.
    *   GCS triggers a Pub/Sub notification to the Task API.
    *   The Task API enqueues an execution task in Cloud Tasks.
    *   Cloud Tasks invokes the private GPU Task Handler via Direct VPC Egress.
    *   The Task Handler processes the image via the Gemma VLM and writes the metadata analysis back to GCS.
    *   The dashboard will update to show the task transitioning from `PENDING` -> `RUNNING` -> `COMPLETED`, displaying the VLM-extracted JSON metadata.
