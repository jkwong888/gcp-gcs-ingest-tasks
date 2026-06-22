import json
import logging
from typing import Optional
from google.cloud import storage

logger = logging.getLogger("taskhandler_vllm.gcs_utils")

# Module-level global storage client
_storage_client: Optional[storage.Client] = None

def init_storage_client() -> None:
    """Initializes the global GCS storage client once at startup."""
    global _storage_client
    if _storage_client is not None:
        logger.warning("GCS Storage Client was already initialized. Re-initializing.")
    logger.info("Initializing global Google Cloud Storage Client...")
    _storage_client = storage.Client()

def get_storage_client() -> storage.Client:
    """Retrieves the initialized GCS storage client, raising an error if uninitialized."""
    global _storage_client
    if _storage_client is None:
        raise RuntimeError(
            "GCS Storage Client is not initialized. "
            "Please call init_storage_client() at application startup."
        )
    return _storage_client

def parse_bucket_path(gcs_path: str) -> tuple[str, str]:
    """Generic path parsing utility to split gs://bucket/path/to/obj into (bucket, path)."""
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"invalid GCS location: {gcs_path}")
    
    path = gcs_path[len("gs://"):]
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"invalid GCS location format: {gcs_path}")
    
    return parts[0], parts[1]

def read_json_from_gcs(bucket_name: str, object_path: str) -> dict:
    """
    Generic GCS helper. Downloads a text blob and parses it as a JSON dictionary.
    Returns an empty dictionary if the blob is not found or fails to read.
    """
    try:
        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_path)
        content = blob.download_as_text()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Could not read JSON from GCS gs://{bucket_name}/{object_path}: {e}")
        return {}

def write_json_to_gcs(bucket_name: str, object_path: str, data: dict) -> None:
    """
    Generic GCS helper. Serializes a dictionary to JSON text and uploads it to GCS.
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    blob.upload_from_string(
        data=json.dumps(data, indent=2),
        content_type="application/json"
    )

def read_bytes_from_gcs(bucket_name: str, object_path: str) -> bytes:
    """
    Generic GCS helper. Downloads a binary blob as raw bytes.
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    return blob.download_as_bytes()
