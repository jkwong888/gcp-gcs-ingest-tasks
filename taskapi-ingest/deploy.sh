#!/bin/bash
#
# Self-contained Deployment Script for Ingestion Task API (Node.js/TypeScript)
# This script builds the Ingestion Task API image using Cloud Build and deploys it to Cloud Run.
# It enforces strict IAM authentication (--no-allow-unauthenticated).
#

set -euo pipefail

# ==============================================================================
# 1. CONFIGURATION VARIABLES
# ==============================================================================
PROJECT_ID="jkwng-cloud-tasks-dev-51c5"
REGION="us-central1"
REGISTRY_PROJECT_ID="jkwng-images"

# Service Settings
SERVICE_NAME="taskapi-ingest"
SERVICE_ACCOUNT="taskapi-ingest@${PROJECT_ID}.iam.gserviceaccount.com"

# Ingestion Settings
BUCKET_NAME="jkwng-data-51c5"
QUEUE_NAME="work-queue-51c5"
TASKS_SERVICE_ACCOUNT_EMAIL="cloud-tasks@${PROJECT_ID}.iam.gserviceaccount.com"

# Task Handler Integration
TASK_HANDLER_URL="" 
TASKHANDLER_SERVICE_NAME="taskhandler"
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

# Ensure we are in the script's directory (taskapi-ingest/)
cd "$(dirname "$0")"

# ==============================================================================
# 2. PREREQUISITE CHECKS
# ==============================================================================
log_info "Checking prerequisites..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed. Please install it first: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# ==============================================================================
# 3. AUTO-DETECT TASK HANDLER URL (IF EMPTY)
# ==============================================================================
if [ -z "${TASK_HANDLER_URL:-}" ]; then
    log_info "TASK_HANDLER_URL is not set. Attempting to auto-detect from Cloud Run service: $TASKHANDLER_SERVICE_NAME..."
    
    DETECTED_URL=$(gcloud run services describe "$TASKHANDLER_SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.url)' 2>/dev/null || true)
        
    if [ -z "$DETECTED_URL" ]; then
        log_error "Could not auto-detect Task Handler URL. Please ensure:"
        log_error "  1. The Task Handler service ($TASKHANDLER_SERVICE_NAME) is deployed in region $REGION."
        log_error "  2. Or, manually populate TASK_HANDLER_URL at the top of this script."
        exit 1
    fi
    
    TASK_HANDLER_URL="$DETECTED_URL"
    log_info "Successfully auto-detected Task Handler URL: $TASK_HANDLER_URL"
fi

# Docker image tag (using pre-existing GCR repository in the registry project)
IMAGE_TAG="gcr.io/${REGISTRY_PROJECT_ID}/${SERVICE_NAME}:latest"

# ==============================================================================
# 4. BUILD & DEPLOY TO CLOUD RUN
# ==============================================================================
log_info "========================================="
log_info "Building and Deploying Ingestion Task API..."
log_info "========================================="

log_info "Submitting Cloud Build for Ingestion Task API..."
gcloud builds submit --project="$PROJECT_ID" --tag "$IMAGE_TAG" .

log_info "Deploying Ingestion Task API to Cloud Run (Private - IAM Secured)..."
gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --image="$IMAGE_TAG" \
    --region="$REGION" \
    --port=8000 \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="BUCKET_NAME=${BUCKET_NAME},QUEUE_NAME=${QUEUE_NAME},PROJECT_ID=${PROJECT_ID},REGION=${REGION},TASK_HANDLER_URL=${TASK_HANDLER_URL},TASKS_SERVICE_ACCOUNT_EMAIL=${TASKS_SERVICE_ACCOUNT_EMAIL}" \
    --quiet

# Retrieve the Ingestion Task API URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')

log_info "========================================="
log_info "INGESTION TASK API DEPLOYMENT COMPLETE!"
log_info "========================================="
log_info "Service URL: $SERVICE_URL (Private - IAM Required)"
log_info "========================================="
