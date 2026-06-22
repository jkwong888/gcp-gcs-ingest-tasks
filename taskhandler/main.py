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

def write_status(client: storage.Client, bucket_name: str, job_id: str, status: str, extra: dict) -> None:
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
        data = {
            "jobId": job_id,
        }
    
    # Update status and updatedAt
    data["status"] = status
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data["updatedAt"] = now_iso
    
    # Track state transition timestamps
    if status == "RUNNING":
        data["startedAt"] = now_iso
    elif status == "COMPLETED":
        data["completedAt"] = now_iso
    elif status == "FAILED":
        data["failedAt"] = now_iso
        
    # Merge any extra fields provided
    data.update(extra)
    
    blob.upload_from_string(
        data=json.dumps(data),
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

    thumbnail_path = f"gs://{bucket_name}/thumbs/{task.job_id}.png"
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
            }
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
                    extra={
                        "error": f"Object not found: {task.path}",
                        "gcsPath": task.path,
                        "thumbnailPath": thumbnail_path
                    }
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
                extra={
                    "error": f"Error accessing object: {e}",
                    "gcsPath": task.path,
                    "thumbnailPath": thumbnail_path
                }
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
                extra={
                    "error": f"Failed to read GCS file: {e}",
                    "gcsPath": task.path,
                    "thumbnailPath": thumbnail_path
                }
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
                extra={
                    "error": f"Failed to decode image: {e}",
                    "gcsPath": task.path,
                    "thumbnailPath": thumbnail_path
                }
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
            extra={
                "gcsPath": task.path,
                "width": width,
                "height": height,
                "format": img_format.lower(),
                "thumbnailPath": thumbnail_path
            }
        )
    except Exception as e:
        logger.error(f"Failed to write COMPLETED status to GCS: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write COMPLETED status: {e}")

    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8090, log_level="info")
