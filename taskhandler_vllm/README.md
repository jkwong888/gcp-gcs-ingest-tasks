# vLLM Task Handler (GPU Service)

This directory houses the GPU-accelerated version of the task handler. It uses **vLLM** to run the Gemma vision-language model (VLM), extracting structured metadata from ingested images.

---

## Local Development & Testing

The project uses **`uv`** for dependency management.

### 1. Setup Virtual Environment
To install all dependencies (including dev tools) locally:
```bash
uv sync
```
*Note: A physical GPU and configured CUDA drivers are required to run the engine locally. If no GPU is present, starting the server will crash on boot.*

### 2. Run Unit Tests (CPU-Compatible)
You can run the unit tests on a CPU-only machine (such as a local laptop or CI runner). The test suite automatically mocks out the CUDA/vLLM engine:
```bash
uv run pytest -v
```

### 3. Local Smoke Testing (Mock Mode)
If `vllm` is not installed or no GPU is detected, the application automatically boots into a **Mock Mode** for local testing:

1. Start the FastAPI server locally (runs on port `8090`):
   ```bash
   python3 main.py
   ```
2. In another terminal, run the smoke test script with a local image to verify the API response format:
   ```bash
   ./run_local_test.py --image /path/to/image.jpg
   ```

---

## Deployment

The service is deployed to Cloud Run using L4 GPUs.

1. Configure your GCP parameters at the top of [deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskhandler_vllm/deploy.sh).
2. Execute the deployment script:
   ```bash
   ./deploy.sh
   ```
3. **Fast Iterations (Skip Image Rebuilds)**: To deploy local Python code changes instantly without recompiling the container image via Cloud Build, run:
   ```bash
   ./deploy.sh --skip-build
   ```

For detailed explanations of the private VPC network, autoscaling limits, and cold-start optimizations, refer to the main [DEPLOYMENT.md](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/DEPLOYMENT.md) guide in the repository root.
