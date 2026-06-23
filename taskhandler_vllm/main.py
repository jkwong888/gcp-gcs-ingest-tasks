import os
# Force vLLM to spawn worker processes instead of forking, preventing CUDA re-initialization crashes.
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
# Enable CUDA Forward Compatibility to run newer CUDA compiled wheels on older host GPU drivers.
os.environ["VLLM_ENABLE_CUDA_COMPATIBILITY"] = "1"

import time
import logging
import traceback
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

# Import modular components
from model import TaskRequest, ImageMetadataAnalysis
from constants import PROMPT_TEMPLATE
from task import load_image_bytes, record_task_status
from vllm_engine import init_vllm_engine
from gcs_utils import init_storage_client
from pipeline import run_pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("taskhandler_vllm.main")

# Filter out high-frequency /health endpoint access logs to reduce noise in Cloud Logging
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        is_health = False
        # Check if the log is a Uvicorn access log and the path is /health
        # Uvicorn format: (client_addr, method, path, http_version, status_code)
        if record.args and len(record.args) >= 3:
            path = record.args[2]
            if path == "/health":
                is_health = True
        # Fallback string check
        elif "/health" in record.getMessage():
            is_health = True

        if is_health:
            # Demote the log level to DEBUG so it is hidden under INFO log levels,
            # but remains fully inspectable if log level is set to DEBUG.
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"

        return True

# Apply the filter to Uvicorn's access log channel
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

# ------------------------------------------------------------------------------
# Config & Lifespan Setup
# ------------------------------------------------------------------------------
init_sleep_sec = int(os.environ.get("INIT_SLEEP_SEC", "0"))
handle_input_sleep_sec = int(os.environ.get("HANDLE_INPUT_SLEEP_SEC", "0"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Saves prompts/schemas, downloads weights if needed, and loads AsyncLLMEngine.
    Instantiates the global storage.Client once to reuse across all requests.
    If MODEL_PATH is missing or GPU/CUDA drivers are unavailable, it fails fast on startup.
    """
    # Verify model path is provided at runtime
    model_path = os.environ.get("MODEL_PATH")
    if not model_path:
        raise ValueError("MODEL_PATH environment variable is required at startup.")

    # Initialize prompts and validation schemas
    app.state.prompt_template = PROMPT_TEMPLATE
    app.state.json_schema = ImageMetadataAnalysis.model_json_schema()

    # Initialize global GCS Client once at startup to avoid per-request latency
    init_storage_client()

    # Simulate slow initialization if configured
    if init_sleep_sec > 0:
        logger.info(f"Simulating slow initialization: sleeping {init_sleep_sec}s...")
        time.sleep(init_sleep_sec)

    # Initialize vLLM engine and AutoProcessor strictly on GPU
    logger.info(f"Initializing vLLM Engine and Processor for model: {model_path}")
    init_vllm_engine(
        model_path=model_path,
        tensor_parallel_size=int(os.environ.get("TENSOR_PARALLEL_SIZE", "1")),
        pipeline_parallel_size=int(os.environ.get("PIPELINE_PARALLEL_SIZE", "1")),
        gpu_memory_utilization=float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.90")),
        max_model_len=int(os.environ.get("MAX_MODEL_LEN")) if os.environ.get("MAX_MODEL_LEN") else None,
        dtype=os.environ.get("DTYPE", "auto"),
        trust_remote_code=os.environ.get("TRUST_REMOTE_CODE", "True").lower() == "true",
    )

    yield
    logger.info("Lifespan shutdown complete.")

app = FastAPI(lifespan=lifespan)

# ------------------------------------------------------------------------------
# API Router Interfaces
# ------------------------------------------------------------------------------

@app.get("/health", response_class=PlainTextResponse)
def health_check():
    """Simple health check endpoint returning 200 OK."""
    return "OK"

@app.post("/", response_model=dict)
async def handle_task(task: TaskRequest, request: Request):
    """
    HTTP POST handler for processing a single image ingestion task.
    Supports either GCS paths, local file paths, or raw base64 image strings.
    Retrieves the global GCS client, records statuses, and runs the ingestion pipeline.
    """
    logger.info(f"Received ingestion task: {task.job_id}")

    # Extract Cloud Tasks metadata headers
    cloud_tasks_meta = {}
    if "x-cloudtasks-taskname" in request.headers:
        cloud_tasks_meta["cloudTasksTaskName"] = request.headers.get("x-cloudtasks-taskname")
    if "x-cloudtasks-taskretrycount" in request.headers:
        cloud_tasks_meta["cloudTasksRetryCount"] = request.headers.get("x-cloudtasks-taskretrycount")
    if "x-cloudtasks-taskexecutioncount" in request.headers:
        cloud_tasks_meta["cloudTasksExecutionCount"] = request.headers.get("x-cloudtasks-taskexecutioncount")

    if cloud_tasks_meta:
        logger.info(f"Detected Cloud Tasks Metadata headers: {cloud_tasks_meta}")

    is_local_debug = not bool(cloud_tasks_meta)

    # 1. Update task status to RUNNING
    logger.info(f"Updating task status to RUNNING for jobId: {task.job_id}")
    try:
        record_task_status(
            job_id=task.job_id,
            status="RUNNING",
            gcs_path=task.path,
            cloud_tasks_meta=cloud_tasks_meta,
            is_local_debug=is_local_debug
        )
    except Exception as e:
        logger.error(f"Failed to record RUNNING status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record RUNNING status: {e}")

    # Simulate processing delay if requested
    if handle_input_sleep_sec > 0:
        logger.info(f"Simulating processing delay of {handle_input_sleep_sec} seconds...")
        time.sleep(handle_input_sleep_sec)

    # 2. Load the image bytes (Generic loader handles GCS, local files, and base64!)
    try:
        image_bytes = load_image_bytes(task.path, task.b64input)
    except Exception as e:
        error_msg = f"Failed to load input image: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        # Log failure status
        record_task_status(
            job_id=task.job_id,
            status="FAILED",
            gcs_path=task.path,
            error_msg=error_msg,
            is_local_debug=is_local_debug
        )
        raise HTTPException(status_code=400, detail=error_msg)

    # 3. Execute the multi-step pipeline (Image props + LLM guided inference)
    try:
        request_id = f"job-{task.job_id}-{time.time()}"
        pipeline_result = await run_pipeline(
            prompt=request.app.state.prompt_template,
            schema=request.app.state.json_schema,
            image_bytes=image_bytes,
            request_id=request_id
        )
    except ValueError as e:
        error_msg = f"Failed to decode or process image: {e}"
        record_task_status(
            job_id=task.job_id,
            status="FAILED",
            gcs_path=task.path,
            error_msg=error_msg,
            is_local_debug=is_local_debug
        )
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = f"Pipeline execution failed: {e}"
        record_task_status(
            job_id=task.job_id,
            status="FAILED",
            gcs_path=task.path,
            error_msg=error_msg,
            is_local_debug=is_local_debug
        )
        raise HTTPException(status_code=500, detail=error_msg)

    # 4. Write COMPLETED status
    logger.info(f"Task COMPLETED for jobId: {task.job_id}")
    try:
        record_task_status(
            job_id=task.job_id,
            status="COMPLETED",
            gcs_path=task.path,
            extra=pipeline_result,
            is_local_debug=is_local_debug
        )
    except Exception as e:
        logger.error(f"Failed to write COMPLETED status: {e}")

    return {"status": "ok", "result": pipeline_result}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8090, log_level="info")
