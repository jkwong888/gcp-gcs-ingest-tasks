# vLLM Task Handler (GPU Alternative)

This directory contains a GPU-accelerated alternative to the original `taskhandler`. It uses **vLLM's `AsyncLLMEngine`** to run a Vision-Language Model (VLM) or Large Language Model (LLM) inside the FastAPI container, processing incoming images (or text payloads) and generating structured JSON task results.

## Key Features

1. **Lifespan Initialization**: The vLLM engine is loaded and GPU memory is profiled during the FastAPI `lifespan` startup. Because model loading is a heavy, blocking operation, the FastAPI server will not start listening on its port (port `8090`) until the model is fully loaded. This ensures that the `/health` check will not respond (i.e., connection refused or timeout) until the LLM is fully loaded into GPU memory and ready to serve requests.
2. **Run:ai GCS Weight Streaming**: To dramatically accelerate model loading and reduce instance cold starts, the handler automatically detects if the `MODEL_PATH` starts with `gs://`. If so, it configures vLLM to use the **Run:ai Model Streamer** (`load_format="runai_streamer"`), streaming weights directly from GCS into accelerator memory. Otherwise, it falls back to standard `auto` loading (useful for HuggingFace or local disk testing).
3. **Inlined Prompts & Schemas (Code-driven)**: To ensure stability, safety, and reproducibility, the model's prompt template and JSON schema (implemented as a Pydantic model `ImageMetadataAnalysis`) are defined directly inline in the code (`constants.py`). This removes the need for external files, making them version-controlled and naturally triggering a redeployment when changed.
4. **Structured Outputs**: Uses vLLM's guided decoding (`GuidedDecodingParams`) to force the model to return valid JSON matching the Pydantic schema, eliminating the need to parse raw model text or handle formatting errors.
5. **Multimodal Support & Pipeline Refactoring**: Executes a robust multi-step pipeline (`run_pipeline` in `pipeline.py`): first decoding the image and extracting dimensions (width, height, format), then invoking the model. If any failure occurs, the full stack trace is logged, and the exception bubbles up as an HTTP response.
6. **Task Attempt, Retry & Job ID Tracking**: Supports deep GCS attempt tracking. Each invocation of the task handler writes a new attempt block to an `attempts` array in `results/{jobId}.json`, capturing:
   - `attemptNumber`: 1-based retry index.
   - `status`: `"RUNNING"`, `"COMPLETED"`, or `"FAILED"`.
   - Timestamps: `startedAt`, `completedAt`, or `failedAt`.
   - **Cloud Tasks Metadata**: Automatically extracts `X-CloudTasks-TaskName`, `X-CloudTasks-TaskRetryCount`, and `X-CloudTasks-TaskExecutionCount` from request headers to tie task results directly to Cloud Tasks history.
   - `result` (on success) or `error` message (on failure).
   - Top-level status fields are preserved for backwards compatibility.
7. **Modular Split-File Architecture**: The codebase is cleanly split into specialized modules for single responsibility:
   - `main.py`: Entry point, lifespan startup coordinator, and HTTP route handlers.
   - `constants.py`: Holds the prompt template string and the Pydantic structured output model.
   - `vllm_engine.py`: Manages model downloads, GCS weight streaming, and vLLM inference execution.
   - `pipeline.py`: Coordinates image property extraction and model calls.
   - `gcs_utils.py`: Manages GCS upload/download and attempt history array logs.
8. **Environment-Friendly Testing**: Includes a mock-based test suite that allows running 100% of unit tests in a lightweight CPU-only local environment without having to install `vllm` or its heavy CUDA/PyTorch dependencies.

---

## Environment Variables

This handler supports all environment variables of the original `taskhandler` plus new ones for configuring the LLM engine:

| Variable | Description | Default / Example |
|---|---|---|
| `INIT_SLEEP_SEC` | Extra simulated initialization delay | `0` |
| `HANDLE_INPUT_SLEEP_SEC` | Extra simulated processing delay | `0` |
| `MODEL_PATH` | HuggingFace model ID or GCS URI (`gs://...`) (**Required**) | `google/paligemma-3b-pt-448` |
| `TENSOR_PARALLEL_SIZE` | Number of GPUs for tensor parallelism | `1` |
| `PIPELINE_PARALLEL_SIZE`| Number of GPUs for pipeline parallelism | `1` |
| `GPU_MEMORY_UTILIZATION`| Fraction of GPU memory to reserve for vLLM | `0.90` |
| `MAX_MODEL_LEN` | Maximum context length of the model | *Auto-detected* |
| `DTYPE` | Data precision (`auto`, `half`, `float16`, `bfloat16`) | `auto` |
| `TRUST_REMOTE_CODE` | Allow running remote code from HuggingFace | `True` |

*Note: The prompt template and JSON schema are defined inline inside the code (`main.py`).*

---

## Local Manual Testing (Smoke Testing)

We have provided a smoke test script `run_local_test.py` that allows you to easily test the running API locally by sending a local image file.

1. Start the task handler locally (it runs in Mock Mode by default if `vllm` is not installed):
   ```bash
   python3 main.py
   ```
2. In another terminal, run the smoke test script with a local image:
   ```bash
   ./run_local_test.py --image /path/to/an/image.jpg
   ```
3. The script will encode the image to base64, send the request to the local API, and print the structured JSON response returned by the handler:
   ```json
   [SUCCESS] HTTP Status Code: 200
   Response JSON:
   {
     "status": "ok",
     "result": {
       "caption": "A mock description of the image",
       "tags": [
         "mock",
         "test"
       ],
       "primary_color": "blue"
     }
   }
   ```
   *(If running on a real GPU machine with vLLM installed and a real model loaded, the response will contain the actual model predictions.)*

---

## Local Development & Testing (No GPU required)

The codebase is initialized as a unified **`uv`** project (`pyproject.toml` & `uv.lock`) for a seamless, fast, and reproducible developer experience. You can run and test the application locally on CPU without a Docker container:

### 1. Setup Local Environment
To create a local virtual environment and install all dependencies (including testing tools like `pytest`), run:
```bash
cd taskhandler_vllm
uv sync
```
This single command automatically creates a `.venv` directory (if not present) and synchronizes all locked dependencies.

### 2. Run the Application Locally
To start the FastAPI task handler locally (on port `8090`), run:
```bash
uv run python main.py
```
This spins up the server in your local virtual environment without needing to activate it manually.

### 3. Run Unit Tests
To run the mocked unit test suite on CPU, run:
```bash
uv run pytest -v
```

---

## Docker Container & uv Integration

The **[Dockerfile](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskhandler_vllm/Dockerfile)** leverages the unified `uv.lock` file to guarantee identical builds:

- It copies the high-performance `uv` binary directly from the official `ghcr.io/astral-sh/uv` multi-stage build image.
- It copies `pyproject.toml` and `uv.lock` and executes `uv sync --system --no-dev --no-cache` to sync the exact locked dependency tree.
- The `--system` flag is used because the base vLLM image has its GPU/CUDA dependencies installed globally in the system Python path. Installing our dependencies globally ensures they can seamlessly access the vLLM engine.
- The `--no-dev` flag ensures that development tools like `pytest` are excluded from the production image.

---

## Deployment to Cloud Run (with GPU)

This service requires a GPU to run. We deploy it to Cloud Run using **NVIDIA L4 GPUs**.

1. Edit the top section of `deploy.sh` with your GCP project configuration.
2. Make the script executable and run it:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

The script will:
- Build the image using Cloud Build (which handles packaging the dependencies via `vllm/vllm-openai:latest`).
- Deploy the service to Cloud Run in a region supporting L4 GPUs (e.g., `us-central1`).
- Allocate **1 GPU (`nvidia-l4`)**, **4 CPUs**, and **16Gi of memory**, and disable CPU throttling so the GPU remains active.
- Set the environment variables, including `MODEL_PATH`.
