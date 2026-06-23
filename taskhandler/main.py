import os
import io
import time
import logging
import base64
import datetime
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image
from google.cloud import storage
from google.api_core.exceptions import NotFound

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("taskhandler")

class TaskStruct(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    b64input: Optional[str] = Field(default=None, alias="b64input")
    path: Optional[str] = Field(default=None, alias="gcsPath")
    job_id: Optional[str] = Field(default=None, alias="jobId")
    signed_url: Optional[str] = Field(default=None, alias="signedUrl")
    session_url: Optional[str] = Field(default=None, alias="sessionUrl")

def parse_bucket_path(gcs_path: str) -> tuple[str, str]:
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"invalid GCS location: {gcs_path}")
    
    path = gcs_path[len("gs://"):]
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"invalid GCS location format: {gcs_path}")
    
    return parts[0], parts[1]

def update_task_status_data(
    existing_data: dict,
    job_id: str,
    status: str,
    gcs_path: Optional[str] = None,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None,
    cloud_tasks_meta: Optional[dict] = None
) -> dict:
    """
    Pure state machine function that updates the task status dictionary.
    Handles transition states (RUNNING, COMPLETED, FAILED), appends retry
    attempts to the history array, and merges Cloud Tasks tracking metadata.
    """
    data = dict(existing_data)  # Create a copy to prevent side-effects
    if "jobId" not in data:
        data["jobId"] = job_id
    if "attempts" not in data:
        data["attempts"] = []
        
    # Automatically resolve GCS path and thumbnail path conventions
    thumbnail_path = None
    if gcs_path and gcs_path.startswith("gs://"):
        data["gcsPath"] = gcs_path
        try:
            bucket_name, _ = parse_bucket_path(gcs_path)
            thumbnail_path = f"gs://{bucket_name}/thumbs/{job_id}.png"
            data["thumbnailPath"] = thumbnail_path
        except Exception:
            pass
        
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data["status"] = status
    data["updatedAt"] = now_iso
    attempts = data["attempts"]
    
    if status == "RUNNING":
        data["startedAt"] = now_iso
        attempt_number = len(attempts) + 1
        new_attempt = {
            "attemptNumber": attempt_number,
            "status": "RUNNING",
            "startedAt": now_iso
        }
        if gcs_path:
            new_attempt["gcsPath"] = gcs_path
        if thumbnail_path:
            new_attempt["thumbnailPath"] = thumbnail_path
        if cloud_tasks_meta:
            new_attempt.update(cloud_tasks_meta)
        attempts.append(new_attempt)
        
    elif status == "COMPLETED":
        data["completedAt"] = now_iso
        if attempts:
            attempts[-1]["status"] = "COMPLETED"
            attempts[-1]["completedAt"] = now_iso
            
            # Build final attempt result payload
            result_payload = {}
            if gcs_path:
                result_payload["gcsPath"] = gcs_path
            if thumbnail_path:
                result_payload["thumbnailPath"] = thumbnail_path
            if extra:
                result_payload.update(extra)
            attempts[-1]["result"] = result_payload
            
        if extra:
            data.update(extra)
            
    elif status == "FAILED":
        data["failedAt"] = now_iso
        if attempts:
            attempts[-1]["status"] = "FAILED"
            attempts[-1]["failedAt"] = now_iso
            attempts[-1]["error"] = error_msg or "Unknown error"
        data["error"] = error_msg or "Unknown error"
        if extra:
            data.update(extra)
            
    return data

def write_status(
    client: storage.Client,
    bucket_name: str,
    job_id: str,
    status: str,
    gcs_path: Optional[str] = None,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None,
    cloud_tasks_meta: Optional[dict] = None
) -> None:
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"results/{job_id}.json")
    
    # Try to load existing status to preserve timestamps (like queuedAt)
    data = {}
    try:
        content = blob.download_as_text()
        data = json.loads(content)
    except Exception as e:
        # If the file doesn't exist or we can't read it, start fresh
        logger.warning(f"Could not read existing status for {job_id}: {e}")
    
    # Transition state machine
    updated_data = update_task_status_data(
        existing_data=data,
        job_id=job_id,
        status=status,
        gcs_path=gcs_path,
        extra=extra,
        error_msg=error_msg,
        cloud_tasks_meta=cloud_tasks_meta
    )
    
    blob.upload_from_string(
        data=json.dumps(updated_data),
        content_type="application/json"
    )

def handle_b64(b64input: str, handle_input_sleep_sec: int):
    logger.info("handling b64 encoded input ...")
    try:
        img_bytes = base64.b64decode(b64input)
        img = Image.open(io.BytesIO(img_bytes))
        width, height = img.size
        logger.info(f"Decoded image format {width}x{height} ...")
    except Exception as e:
        logger.error(f"error decoding image: {e}")
        raise HTTPException(status_code=400, detail="Invalid image data")

    # simulate work
    time.sleep(handle_input_sleep_sec)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Read config from env
    init_sleep_sec = int(os.getenv("INIT_SLEEP_SEC", "30"))
    handle_input_sleep_sec = int(os.getenv("HANDLE_INPUT_SLEEP_SEC", "2"))
    
    app.state.init_sleep_sec = init_sleep_sec
    app.state.handle_input_sleep_sec = handle_input_sleep_sec
    
    # 2. Initialize GCS Client
    logger.info("Initializing GCS Client...")
    app.state.gcs_client = storage.Client()
    
    # 3. Simulate initialization sleep
    logger.info(f"Simulating initialization of {init_sleep_sec} seconds ...")
    time.sleep(init_sleep_sec)
    
    logger.info("Initialization complete. Server ready.")
    yield

app = FastAPI(lifespan=lifespan)

@app.api_route("/health", methods=["GET", "POST"])
async def health_check():
    logger.info("Health check request received: OK")
    return PlainTextResponse("OK")

@app.post("/")
async def handle_task(request: Request, task: TaskStruct):
    logger.info(f"handling request: POST {request.url.path}, {task}")
    
    handle_input_sleep_sec = request.app.state.handle_input_sleep_sec
    client = request.app.state.gcs_client

    if task.b64input is not None:
        handle_b64(task.b64input, handle_input_sleep_sec)
        return {"status": "ok"}

    if not task.job_id:
        logger.error("jobId is required")
        raise HTTPException(status_code=400, detail="jobId is required")

    if not task.path:
        logger.error("gcsPath is required")
        raise HTTPException(status_code=400, detail="gcsPath is required")

    try:
        bucket_name, obj_path = parse_bucket_path(task.path)
    except ValueError as e:
        logger.info(f"Error parsing path {task.path}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # Extract Cloud Tasks metadata headers
    cloud_tasks_meta = {}
    if "x-cloudtasks-taskname" in request.headers:
        cloud_tasks_meta["cloudTasksTaskName"] = request.headers.get("x-cloudtasks-taskname")
    if "x-cloudtasks-taskretrycount" in request.headers:
        cloud_tasks_meta["cloudTasksRetryCount"] = request.headers.get("x-cloudtasks-taskretrycount")
    if "x-cloudtasks-taskexecutioncount" in request.headers:
        cloud_tasks_meta["cloudTasksExecutionCount"] = request.headers.get("x-cloudtasks-taskexecutioncount")

    logger.info(f"Updating task status to RUNNING for jobId: {task.job_id}")
    try:
        write_status(
            client=client,
            bucket_name=bucket_name,
            job_id=task.job_id,
            status="RUNNING",
            gcs_path=task.path,
            cloud_tasks_meta=cloud_tasks_meta
        )
    except Exception as e:
        logger.error(f"Failed to write RUNNING status to GCS: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write RUNNING status: {e}")

    logger.info(f"Simulating processing delay of {handle_input_sleep_sec} seconds...")
    time.sleep(handle_input_sleep_sec)

    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(obj_path)
        blob.reload()  # Check existence and fetch metadata
    except Exception as e:
        if isinstance(e, NotFound):
            logger.error(f"Object not found in bucket {bucket_name}: {obj_path}")
            try:
                write_status(
                    client=client,
                    bucket_name=bucket_name,
                    job_id=task.job_id,
                    status="FAILED",
                    gcs_path=task.path,
                    error_msg=f"Object not found: {task.path}"
                )
            except Exception as we:
                logger.error(f"Failed to write FAILED status to GCS: {we}")
            raise HTTPException(status_code=404, detail=f"Object not found: {task.path}")
        
        logger.error(f"error fetching object attrs: {e}")
        try:
            write_status(
                client=client,
                bucket_name=bucket_name,
                job_id=task.job_id,
                status="FAILED",
                gcs_path=task.path,
                error_msg=f"Error accessing object: {e}"
            )
        except Exception as we:
            logger.error(f"Failed to write FAILED status to GCS: {we}")
        raise HTTPException(status_code=500, detail=f"Error accessing object: {e}")

    try:
        img_bytes = blob.download_as_bytes()
    except Exception as e:
        logger.error(f"Failed to read GCS file: {e}")
        try:
            write_status(
                client=client,
                bucket_name=bucket_name,
                job_id=task.job_id,
                status="FAILED",
                gcs_path=task.path,
                error_msg=f"Failed to read GCS file: {e}"
            )
        except Exception as we:
            logger.error(f"Failed to write FAILED status to GCS: {we}")
        raise HTTPException(status_code=500, detail=f"Failed to read GCS file: {e}")

    try:
        img = Image.open(io.BytesIO(img_bytes))
        width, height = img.size
        img_format = img.format or "UNKNOWN"
        logger.info(f"Successfully decoded image: format {img_format}, {width}x{height}")
    except Exception as e:
        logger.error(f"Failed to decode image: {e}")
        try:
            write_status(
                client=client,
                bucket_name=bucket_name,
                job_id=task.job_id,
                status="FAILED",
                gcs_path=task.path,
                error_msg=f"Failed to decode image: {e}"
            )
        except Exception as we:
            logger.error(f"Failed to write FAILED status to GCS: {we}")
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {e}")

    logger.info(f"Task COMPLETED for jobId: {task.job_id}")
    try:
        write_status(
            client=client,
            bucket_name=bucket_name,
            job_id=task.job_id,
            status="COMPLETED",
            gcs_path=task.path,
            extra={
                "width": width,
                "height": height,
                "format": img_format.lower()
            }
        )
    except Exception as e:
        logger.error(f"Failed to write COMPLETED status to GCS: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write COMPLETED status: {e}")

    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8090, log_level="info")
