import os
import json
import base64
import datetime
import logging
from typing import Optional

# Import generic GCS helpers from infrastructure layer
from gcs_utils import read_json_from_gcs, write_json_to_gcs, read_bytes_from_gcs

logger = logging.getLogger("taskhandler_vllm.task")

def load_image_bytes(
    path: Optional[str],
    b64input: Optional[str]
) -> bytes:
    """
    Generic task input loader. Resolves and loads raw image bytes from 
    either a base64 string, a GCS URI (gs://...), or a local file path.
    Hides all GCS and file system details from the API router.
    """
    if b64input:
        logger.info("Decoding image from base64 input...")
        return base64.b64decode(b64input)
    
    if path:
        if path.startswith("gs://"):
            logger.info(f"Downloading image from GCS path: {path} ...")
            from gcs_utils import parse_bucket_path
            bucket_name, object_path = parse_bucket_path(path)
            return read_bytes_from_gcs(bucket_name, object_path)
        else:
            logger.info(f"Loading image from local file path: {path} ...")
            with open(path, "rb") as f:
                return f.read()
                
    raise ValueError("Neither b64input nor path was provided in the task request.")

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
    Automatically resolves GCS/local path conventions and generates thumbnails.
    """
    data = dict(existing_data)  # Create a copy to prevent side-effects
    if "jobId" not in data:
        data["jobId"] = job_id
    if "attempts" not in data:
        data["attempts"] = []
        
    # Automatically resolve GCS/local path and thumbnail path conventions
    thumbnail_path = None
    if gcs_path and gcs_path.startswith("gs://"):
        data["gcsPath"] = gcs_path
        from gcs_utils import parse_bucket_path
        try:
            bucket_name, _ = parse_bucket_path(gcs_path)
            thumbnail_path = f"gs://{bucket_name}/thumbs/{job_id}.png"
            data["thumbnailPath"] = thumbnail_path
        except Exception:
            pass
    elif gcs_path:
        data["gcsPath"] = gcs_path
        thumbnail_path = f"local_runs/thumbs/{job_id}.png"
        data["thumbnailPath"] = thumbnail_path
        
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
    bucket_name: str, 
    job_id: str, 
    status: str, 
    gcs_path: Optional[str] = None,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None,
    cloud_tasks_meta: Optional[dict] = None
) -> None:
    """
    Task Status GCS Writer. 
    Loads the existing status JSON from GCS using generic helpers, 
    delegates the state transition to the pure update_task_status_data state machine,
    and uploads the updated status back to GCS.
    """
    object_path = f"results/{job_id}.json"
    
    # 1. Read existing JSON (or start fresh if not found)
    data = read_json_from_gcs(bucket_name, object_path)
    
    # 2. Transition state machine
    updated_data = update_task_status_data(
        existing_data=data,
        job_id=job_id,
        status=status,
        gcs_path=gcs_path,
        extra=extra,
        error_msg=error_msg,
        cloud_tasks_meta=cloud_tasks_meta
    )
    
    # 3. Write back to GCS using generic helpers
    write_json_to_gcs(bucket_name, object_path, updated_data)

def write_local_status(
    job_id: str,
    status: str,
    gcs_path: Optional[str] = None,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None
) -> None:
    """
    Local I/O wrapper that reads from and writes to the local file system.
    Delegates the core state transition logic to the pure update_task_status_data.
    """
    os.makedirs("local_runs", exist_ok=True)
    local_path = f"local_runs/{job_id}.json"
    
    data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r") as f:
                data = json.load(f)
        except Exception:
            pass
            
    updated_data = update_task_status_data(
        existing_data=data,
        job_id=job_id,
        status=status,
        gcs_path=gcs_path,
        extra=extra,
        error_msg=error_msg
    )
    
    # Tag local debug attempts for ease of identification
    if status == "RUNNING" and updated_data.get("attempts"):
        updated_data["attempts"][-1]["isLocalDebug"] = True
        
    with open(local_path, "w") as f:
        json.dump(updated_data, f, indent=2)
    logger.info(f"Wrote local debug status to {local_path}")

def record_task_status(
    job_id: str,
    status: str,
    gcs_path: Optional[str] = None,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None,
    cloud_tasks_meta: Optional[dict] = None,
    is_local_debug: bool = False
) -> None:
    """
    Unified orchestrator to record task status.
    Writes to GCS if gcs_path is a GCS URI (gs://...), and writes to local disk if is_local_debug is True.
    Hides all bucket parsing and GCS write checks from the calling router.
    """
    if gcs_path and gcs_path.startswith("gs://") and not is_local_debug:
        from gcs_utils import parse_bucket_path
        bucket_name, _ = parse_bucket_path(gcs_path)
        
        # Let exceptions bubble up here so that caller can handle crucial GCS failures
        write_status(
            bucket_name=bucket_name,
            job_id=job_id,
            status=status,
            gcs_path=gcs_path,
            extra=extra,
            error_msg=error_msg,
            cloud_tasks_meta=cloud_tasks_meta
        )
            
    if is_local_debug:
        try:
            write_local_status(
                job_id=job_id,
                status=status,
                gcs_path=gcs_path,
                extra=extra,
                error_msg=error_msg
            )
        except Exception as e:
            logger.error(f"Failed to write local status for job {job_id}: {e}")
