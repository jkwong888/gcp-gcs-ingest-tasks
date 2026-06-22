#!/bin/bash
#
# Self-contained Deployment Script for vLLM Task Handler (Python FastAPI + vLLM)
# This script builds the Task Handler image using Cloud Build and deploys it to Cloud Run with GPU.
#

set -euo pipefail

# ==============================================================================
# 1. CONFIGURATION VARIABLES
# ==============================================================================
# PLEASE UPDATE THESE VARIABLES FOR YOUR GCP ENVIRONMENT
# ==============================================================================
PROJECT_ID="jkwng-cloud-tasks-dev-51c5"
REGION="us-central1"
REGISTRY_PROJECT_ID="jkwng-images"

# Service Settings
SERVICE_NAME="taskhandler-vllm"
SERVICE_ACCOUNT="taskhandler@${PROJECT_ID}.iam.gserviceaccount.com"

# Task Handler Environment Variables
INIT_SLEEP_SEC=0
HANDLE_INPUT_SLEEP_SEC=0

# vLLM Model Settings
MODEL_PATH="gs://jkwng-model-data/models/google/gemma-4-12B-it-qat-w4a16-ct" # Replace with your target HuggingFace VLM or LLM model
TENSOR_PARALLEL_SIZE=1
GPU_MEMORY_UTILIZATION=0.90
TRUST_REMOTE_CODE="True"

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

# Ensure we are in the script's directory (taskhandler_vllm/)
cd "$(dirname "$0")"

# ==============================================================================
# 2. PREREQUISITE CHECKS
# ==============================================================================
log_info "Checking prerequisites..."

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed. Please install it first: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if [ "$PROJECT_ID" == "your-gcp-project-id" ]; then
    log_error "Please edit this script and replace the placeholder PROJECT_ID at the top of the file."
    exit 1
fi

# Docker image tag (using pre-existing GCR repository in the registry project)
IMAGE_TAG="gcr.io/${REGISTRY_PROJECT_ID}/${SERVICE_NAME}:latest"

# ==============================================================================
# 3. BUILD & DEPLOY TO CLOUD RUN (WITH GPU)
# ==============================================================================
log_info "========================================="
log_info "Building and Deploying vLLM Task Handler..."
log_info "========================================="

log_info "Submitting Cloud Build for vLLM Task Handler..."
# We run Cloud Build from the directory of the script (which is taskhandler_vllm/)
gcloud builds submit --project="$PROJECT_ID" --tag "$IMAGE_TAG" .

log_info "Deploying vLLM Task Handler to Cloud Run with GPU (Private)..."
# We deploy with:
# - --gpu=1 and --gpu-type=nvidia-l4 for GPU acceleration
# - --cpu=4 and --memory=16Gi (minimum resources required for GPU instances)
# - --no-cpu-throttling (required for GPU instances so GPU remains active)
gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --image="$IMAGE_TAG" \
    --region="$REGION" \
    --port=8090 \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --gpu=1 \
    --gpu-type=nvidia-l4 \
    --cpu=4 \
    --memory=16Gi \
    --no-cpu-throttling \
    --cpu-boost \
    --timeout=600 \
    --set-env-vars="MODEL_PATH=${MODEL_PATH}" \
    --quiet

# Retrieve the Task Handler URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')

log_info "========================================="
log_info "vLLM TASK HANDLER DEPLOYMENT COMPLETE!"
log_info "========================================="
log_info "Service URL: $SERVICE_URL (Private)"
log_info "========================================="
