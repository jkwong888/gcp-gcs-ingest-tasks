#!/bin/bash
#
# Self-contained Deployment Script for Task Handler (Go)
# This script builds the Task Handler image using Cloud Build and deploys it to Cloud Run.
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

# Service Settings
SERVICE_NAME="taskhandler"
SERVICE_ACCOUNT="taskhandler@${PROJECT_ID}.iam.gserviceaccount.com"

# Task Handler Environment Variables
INIT_SLEEP_SEC=5
HANDLE_INPUT_SLEEP_SEC=2
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

# Ensure we are in the script's directory (taskhandler/)
cd "$(dirname "$0")"

# ==============================================================================
# 2. PREREQUISITE CHECKS
# ==============================================================================
log_info "Checking prerequisites..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed. Please install it first: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if project is configured
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$CURRENT_PROJECT" ]; then
    log_warn "No default project set in gcloud. Setting to: $PROJECT_ID"
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
if [ "$PROJECT_ID" == "your-gcp-project-id" ]; then
    log_error "Please edit this script and replace the placeholder PROJECT_ID at the top of the file."
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

# Docker image tag
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO_NAME}/${SERVICE_NAME}:latest"

# ==============================================================================
# 4. BUILD & DEPLOY TO CLOUD RUN
# ==============================================================================
log_info "========================================="
log_info "Building and Deploying Task Handler..."
log_info "========================================="

log_info "Submitting Cloud Build for Task Handler..."
# We run Cloud Build from the directory of the script (which is taskhandler/)
gcloud builds submit --tag "$IMAGE_TAG" .

log_info "Deploying Task Handler to Cloud Run (Private)..."
gcloud run deploy "$SERVICE_NAME" \
    --image="$IMAGE_TAG" \
    --region="$REGION" \
    --port=8090 \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="INIT_SLEEP_SEC=${INIT_SLEEP_SEC},HANDLE_INPUT_SLEEP_SEC=${HANDLE_INPUT_SLEEP_SEC}" \
    --quiet

# Retrieve the Task Handler URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')

log_info "========================================="
log_info "TASK HANDLER DEPLOYMENT COMPLETE!"
log_info "========================================="
log_info "Service URL: $SERVICE_URL (Private)"
log_info "========================================="
