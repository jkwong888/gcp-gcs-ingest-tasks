#!/bin/bash
#
# Unified Deployment Script for Task API and Task Handler
# This script builds container images using Cloud Build, pushes them to Artifact Registry,
# and deploys them to separate Cloud Run services with correct environment variables.
#

set -euo pipefail

# ==============================================================================
# 1. CONFIGURATION VARIABLES
# ==============================================================================
# PLEASE UPDATE THESE VARIABLES FOR YOUR GCP ENVIRONMENT
# ==============================================================================
PROJECT_ID="your-gcp-project-id"
REGION="us-central1"
AR_REPO_NAME="tasks-repo"

# Service Accounts
TASKAPI_SA="taskapi@${PROJECT_ID}.iam.gserviceaccount.com"
TASKHANDLER_SA="taskhandler@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_QUEUE_SA="cloud-tasks@${PROJECT_ID}.iam.gserviceaccount.com"
STORAGE_SA="storage@${PROJECT_ID}.iam.gserviceaccount.com"

# Task API Environment Variables
BUCKET_NAME="your-gcs-bucket-name"
BUCKET_PREFIX="input"
QUEUE_NAME="work-queue"

# Task Handler Environment Variables
INIT_SLEEP_SEC=5
HANDLE_INPUT_SLEEP_SEC=2

# Service Names (as deployed on Cloud Run)
TASKHANDLER_SERVICE="taskhandler"
TASKAPI_SERVICE="taskapi"
# ==============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure we are in the script's directory
cd "$(dirname "$0")"

# ==============================================================================
# 2. PREREQUISITE CHECKS
# ==============================================================================
log_info "Checking prerequisites..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed. Please install it first: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated and project is set
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$CURRENT_PROJECT" ]; then
    log_warn "No default project set in gcloud. Attempting to set project to: $PROJECT_ID"
    gcloud config set project "$PROJECT_ID"
elif [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    log_warn "Current gcloud project ($CURRENT_PROJECT) does not match configured PROJECT_ID ($PROJECT_ID)."
    read -p "Do you want to switch gcloud project to $PROJECT_ID? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gcloud config set project "$PROJECT_ID"
    else
        log_error "Project mismatch. Exiting."
        exit 1
    fi
fi

# Check if placeholders are still present
if [ "$PROJECT_ID" == "your-gcp-project-id" ] || [ "$BUCKET_NAME" == "your-gcs-bucket-name" ]; then
    log_error "Please edit this script and replace the placeholder values (PROJECT_ID, BUCKET_NAME, etc.) at the top of the file."
    exit 1
fi

# ==============================================================================
# 3. SETUP ARTIFACT REGISTRY
# ==============================================================================
log_info "Verifying Artifact Registry repository: $AR_REPO_NAME in $REGION..."
if ! gcloud artifacts repositories describe "$AR_REPO_NAME" --location="$REGION" &>/dev/null; then
    log_info "Repository $AR_REPO_NAME not found. Creating..."
    gcloud artifacts repositories create "$AR_REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="Docker repository for tasks services" \
        --quiet
    log_info "Repository created successfully."
else
    log_info "Repository $AR_REPO_NAME already exists."
fi

# Docker image tags
TASKHANDLER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO_NAME}/${TASKHANDLER_SERVICE}:latest"
TASKAPI_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO_NAME}/${TASKAPI_SERVICE}:latest"

# ==============================================================================
# 4. BUILD & DEPLOY TASK HANDLER
# ==============================================================================
log_info "========================================="
log_info "1. Building and Deploying Task Handler..."
log_info "========================================="

log_info "Submitting Cloud Build for Task Handler..."
gcloud builds submit --tag "$TASKHANDLER_IMAGE" ./taskhandler

log_info "Deploying Task Handler to Cloud Run (Private)..."
gcloud run deploy "$TASKHANDLER_SERVICE" \
    --image="$TASKHANDLER_IMAGE" \
    --region="$REGION" \
    --port=8090 \
    --no-allow-unauthenticated \
    --service-account="$TASKHANDLER_SA" \
    --set-env-vars="INIT_SLEEP_SEC=${INIT_SLEEP_SEC},HANDLE_INPUT_SLEEP_SEC=${HANDLE_INPUT_SLEEP_SEC}" \
    --quiet

# Retrieve the Task Handler URL
TASK_HANDLER_URL=$(gcloud run services describe "$TASKHANDLER_SERVICE" --region="$REGION" --format='value(status.url)')
log_info "Task Handler deployed successfully. URL: $TASK_HANDLER_URL"

# ==============================================================================
# 5. BUILD & DEPLOY TASK API
# ==============================================================================
log_info "========================================="
log_info "2. Building and Deploying Task API..."
log_info "========================================="

log_info "Submitting Cloud Build for Task API..."
gcloud builds submit --tag "$TASKAPI_IMAGE" ./taskapi

log_info "Deploying Task API to Cloud Run (Public)..."
gcloud run deploy "$TASKAPI_SERVICE" \
    --image="$TASKAPI_IMAGE" \
    --region="$REGION" \
    --port=8000 \
    --allow-unauthenticated \
    --service-account="$TASKAPI_SA" \
    --set-env-vars="BUCKET_NAME=${BUCKET_NAME},BUCKET_PREFIX=${BUCKET_PREFIX},QUEUE_NAME=${QUEUE_NAME},PROJECT_ID=${PROJECT_ID},REGION=${REGION},TASK_HANDLER_URL=${TASK_HANDLER_URL},TASKS_SERVICE_ACCOUNT_EMAIL=${TASKS_QUEUE_SA},STORAGE_SERVICE_ACCOUNT_EMAIL=${STORAGE_SA}" \
    --quiet

# Retrieve the Task API URL
TASK_API_URL=$(gcloud run services describe "$TASKAPI_SERVICE" --region="$REGION" --format='value(status.url)')

log_info "========================================="
log_info "DEPLOYMENT COMPLETE!"
log_info "========================================="
log_info "Task Handler URL: $TASK_HANDLER_URL (Private)"
log_info "Task API URL:     $TASK_API_URL (Public)"
log_info "========================================="
log_info "Next Steps:"
log_info "1. If you haven't already, ensure your GCS Bucket [${BUCKET_NAME}] is configured with Object Notifications."
log_info "2. Make sure your PubSub subscription is pointing to: ${TASK_API_URL}/uploadNotification"
log_info "3. Open the Task API Dashboard in your browser: ${TASK_API_URL}/"
log_info "========================================="
