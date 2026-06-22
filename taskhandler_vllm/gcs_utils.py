import json
import datetime
import logging
from typing import Optional
from google.cloud import storage

logger = logging.getLogger("taskhandler_vllm.gcs_utils")

def parse_bucket_path(gcs_path: str) -> tuple[str, str]:
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"invalid GCS location: {gcs_path}")
    
    path = gcs_path[len("gs://"):]
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"invalid GCS location format: {gcs_path}")
    
    return parts[0], parts[1]

def write_status(
    client: storage.Client, 
    bucket_name: str, 
    job_id: str, 
    status: str, 
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None,
    cloud_tasks_meta: Optional[dict] = None
) -> None:
    """
    Writes the task status back to GCS at results/{job_id}.json.
    Tracks every task invocation/retry inside an 'attempts' array.
    Also merges Cloud Tasks metadata (headers) into the active attempt for distributed tracking.
    """
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"results/{job_id}.json")
    
    data = {}
    try:
        content = blob.download_as_text()
        data = json.loads(content)
    except Exception as e:
        logger.warning(f"Could not read existing status for {job_id}: {e}. Starting fresh.")
        data = {
            "jobId": job_id,
            "attempts": []
        }
        
    if "attempts" not in data:
        data["attempts"] = []
        
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data["status"] = status
    data["updatedAt"] = now_iso
    attempts = data["attempts"]
    
    if status == "RUNNING":
        data["startedAt"] = now_iso
        # Start a new attempt tracking block
        attempt_number = len(attempts) + 1
        new_attempt = {
            "attemptNumber": attempt_number,
            "status": "RUNNING",
            "startedAt": now_iso
        }
        # Merge Cloud Tasks metadata if provided (Task Name, Retry Count, Execution Count)
        if cloud_tasks_meta:
            new_attempt.update(cloud_tasks_meta)
            
        attempts.append(new_attempt)
        
    elif status == "COMPLETED":
        data["completedAt"] = now_iso
        # Update the latest attempt in the history
        if attempts:
            attempts[-1]["status"] = "COMPLETED"
            attempts[-1]["completedAt"] = now_iso
            attempts[-1]["result"] = extra or {}
        if extra:
            data.update(extra)
            
    elif status == "FAILED":
        data["failedAt"] = now_iso
        # Update the latest attempt in the history
        if attempts:
            attempts[-1]["status"] = "FAILED"
            attempts[-1]["failedAt"] = now_iso
            attempts[-1]["error"] = error_msg or "Unknown error"
        data["error"] = error_msg or "Unknown error"
        if extra:
            data.update(extra)
            
    blob.upload_from_string(
        data=json.dumps(data, indent=2),
        content_type="application/json"
    )

def write_local_status(
    job_id: str,
    status: str,
    extra: Optional[dict] = None,
    error_msg: Optional[str] = None
) -> None:
    """
    Writes the task status to the local disk at local_runs/{job_id}.json.
    Helps with local debugging and offline execution (e.g. run_local_test.py).
    """
    import os
    os.makedirs("local_runs", exist_ok=True)
    local_path = f"local_runs/{job_id}.json"
    
    data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r") as f:
                data = json.load(f)
        except Exception:
            pass
            
    if not data:
        data = {
            "jobId": job_id,
            "attempts": []
        }
        
    if "attempts" not in data:
        data["attempts"] = []
        
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
            "startedAt": now_iso,
            "isLocalDebug": True
        }
        attempts.append(new_attempt)
        
    elif status == "COMPLETED":
        data["completedAt"] = now_iso
        if attempts:
            attempts[-1]["status"] = "COMPLETED"
            attempts[-1]["completedAt"] = now_iso
            attempts[-1]["result"] = extra or {}
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
            
    with open(local_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Wrote local debug status to {local_path}")
