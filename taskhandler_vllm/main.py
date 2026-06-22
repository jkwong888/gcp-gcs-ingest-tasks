import os
import time
import logging
import base64
import json
import traceback
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ConfigDict
from PIL import UnidentifiedImageError
from google.cloud import storage

# Import modular components
from constants import ImageMetadataAnalysis, PROMPT_TEMPLATE
from gcs_utils import parse_bucket_path, write_status, write_local_status
from vllm_engine import init_vllm_engine
from pipeline import run_pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("taskhandler_vllm")

# ==============================================================================
# DATA MODELS FOR TASK PAYLOAD
# ==============================================================================
class TaskStruct(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    b64input: Optional[str] = Field(default=None, alias="b64input")
    path: Optional[str] = Field(default=None, alias="gcsPath")
    job_id: Optional[str] = Field(default=None, alias="jobId")
    signed_url: Optional[str] = Field(default=None, alias="signedUrl")
    session_url: Optional[str] = Field(default=None, alias="sessionUrl")

# ==============================================================================
# FASTAPI LIFESPAN & COORDINATION
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Read configuration from env
    init_sleep_sec = int(os.getenv("INIT_SLEEP_SEC", "0"))
    handle_input_sleep_sec = int(os.getenv("HANDLE_INPUT_SLEEP_SEC", "0"))
    
    app.state.init_sleep_sec = init_sleep_sec
    app.state.handle_input_sleep_sec = handle_input_sleep_sec
    
    # 2. Initialize GCS Client
    logger.info("Initializing GCS Client...")
    app.state.gcs_client = storage.Client()
    
    # 3. Export inlined Pydantic schema to JSON schema dictionary
    app.state.json_schema = ImageMetadataAnalysis.model_json_schema()
    app.state.prompt_template = PROMPT_TEMPLATE

    # 4. Resolve Model Path
    model_path = os.getenv("MODEL_PATH")
    if not model_path:
        raise ValueError("MODEL_PATH environment variable is required")

    tensor_parallel_size = int(os.getenv("TENSOR_PARALLEL_SIZE", "1"))
    pipeline_parallel_size = int(os.getenv("PIPELINE_PARALLEL_SIZE", "1"))
    gpu_memory_utilization = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.90"))
    max_model_len = os.getenv("MAX_MODEL_LEN")
    max_model_len = int(max_model_len) if max_model_len else None
    dtype = os.getenv("DTYPE", "auto")
    trust_remote_code = os.getenv("TRUST_REMOTE_CODE", "False").lower() in ("true", "1", "yes")

    # 5. Initialize modular vLLM engine (blocks until model is loaded in GPU memory)
    app.state.engine = init_vllm_engine(
        model_path=model_path,
        tensor_parallel_size=tensor_parallel_size,
        pipeline_parallel_size=pipeline_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        dtype=dtype,
        trust_remote_code=trust_remote_code
    )

    # Optional initialization sleep
    if init_sleep_sec > 0:
        logger.info(f"Simulating initialization sleep of {init_sleep_sec} seconds ...")
        time.sleep(init_sleep_sec)
    
    logger.info("Initialization complete. Server ready to accept traffic.")
    yield

app = FastAPI(lifespan=lifespan)

# ==============================================================================
# ROUTERS AND ENDPOINTS
# ==============================================================================
@app.api_route("/health", methods=["GET", "POST"])
async def health_check():
    logger.info("Health check request received: OK")
    return PlainTextResponse("OK")

@app.post("/")
async def handle_task(request: Request, task: TaskStruct):
    logger.info(f"handling request: POST {request.url.path}, {task}")
    
    handle_input_sleep_sec = request.app.state.handle_input_sleep_sec
    client = request.app.state.gcs_client
    engine = request.app.state.engine

    if not task.job_id:
        logger.error("jobId is required")
        raise HTTPException(status_code=400, detail="jobId is required")

    if not task.path and not task.b64input:
        logger.error("Either gcsPath or b64input is required")
        raise HTTPException(status_code=400, detail="Either gcsPath or b64input is required")

    bucket_name = None
    obj_path = None
    thumbnail_path = None

    if task.path:
        try:
            bucket_name, obj_path = parse_bucket_path(task.path)
            thumbnail_path = f"gs://{bucket_name}/thumbs/{task.job_id}.png"
        except ValueError as e:
            logger.info(f"Error parsing path {task.path}: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    # EXTRACT CLOUD TASKS METADATA FROM HEADERS
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

    # 1. Update task status to RUNNING (if GCS). Logs attempt started & Cloud Tasks ID.
    if bucket_name:
        logger.info(f"Updating task status to RUNNING for jobId: {task.job_id}")
        try:
            write_status(
                client=client,
                bucket_name=bucket_name,
                job_id=task.job_id,
                status="RUNNING",
                extra={
                    "gcsPath": task.path,
                    "thumbnailPath": thumbnail_path
                },
                cloud_tasks_meta=cloud_tasks_meta
            )
        except Exception as e:
            logger.error(f"Failed to write RUNNING status to GCS: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to write RUNNING status: {e}")

    if is_local_debug:
        try:
            write_local_status(
                job_id=task.job_id,
                status="RUNNING",
                extra={
                    "gcsPath": task.path,
                    "thumbnailPath": thumbnail_path
                }
            )
        except Exception as e:
            logger.error(f"Failed to write local RUNNING status: {e}")

    # Simulate processing delay if requested
    if handle_input_sleep_sec > 0:
        logger.info(f"Simulating processing delay of {handle_input_sleep_sec} seconds...")
        time.sleep(handle_input_sleep_sec)

    # 2. Load the image bytes
    image_bytes = b""
    try:
        if task.b64input:
            logger.info("Decoding image from base64 input...")
            image_bytes = base64.b64decode(task.b64input)
        elif task.path:
            logger.info(f"Downloading image from GCS path: {task.path} ...")
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(obj_path)
            image_bytes = blob.download_as_bytes()
    except Exception as e:
        error_msg = f"Failed to load input image: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        if bucket_name:
            try:
                write_status(
                    client=client,
                    bucket_name=bucket_name,
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write FAILED status to GCS: {we}")
        if is_local_debug:
            try:
                write_local_status(
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write local FAILED status: {we}")
        raise HTTPException(status_code=400, detail=error_msg)

    # 3. Execute the multi-step pipeline (Image props + LLM guided inference)
    try:
        request_id = f"job-{task.job_id}-{time.time()}"
        pipeline_result = await run_pipeline(
            engine=engine,
            prompt=request.app.state.prompt_template,
            schema=request.app.state.json_schema,
            image_bytes=image_bytes,
            request_id=request_id
        )
    except (UnidentifiedImageError, ValueError) as e:
        error_msg = f"Failed to decode or process image: {e}"
        if bucket_name:
            try:
                write_status(
                    client=client,
                    bucket_name=bucket_name,
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write FAILED status to GCS: {we}")
        if is_local_debug:
            try:
                write_local_status(
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write local FAILED status: {we}")
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = f"Pipeline execution failed: {e}"
        if bucket_name:
            try:
                write_status(
                    client=client,
                    bucket_name=bucket_name,
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write FAILED status to GCS: {we}")
        if is_local_debug:
            try:
                write_local_status(
                    job_id=task.job_id,
                    status="FAILED",
                    error_msg=error_msg,
                    extra={
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
                )
            except Exception as we:
                logger.error(f"Failed to write local FAILED status: {we}")
        raise HTTPException(status_code=500, detail=error_msg)

    # 4. Write COMPLETED status to GCS
    if bucket_name:
        logger.info(f"Task COMPLETED for jobId: {task.job_id}")
        try:
            result_payload = {
                "gcsPath": task.path,
                "width": pipeline_result["width"],
                "height": pipeline_result["height"],
                "format": pipeline_result["format"],
                "thumbnailPath": thumbnail_path,
                "llm_analysis": pipeline_result["llm_analysis"]
            }
            write_status(
                client=client,
                bucket_name=bucket_name,
                job_id=task.job_id,
                status="COMPLETED",
                extra=result_payload
            )
        except Exception as e:
            logger.error(f"Failed to write COMPLETED status to GCS: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to write COMPLETED status: {e}")

    if is_local_debug:
        try:
            result_payload = {
                "gcsPath": task.path,
                "width": pipeline_result["width"],
                "height": pipeline_result["height"],
                "format": pipeline_result["format"],
                "thumbnailPath": thumbnail_path,
                "llm_analysis": pipeline_result["llm_analysis"]
            }
            write_local_status(
                job_id=task.job_id,
                status="COMPLETED",
                extra=result_payload
            )
        except Exception as e:
            logger.error(f"Failed to write local COMPLETED status: {e}")

    return {"status": "ok", "result": pipeline_result}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8090, log_level="info")
