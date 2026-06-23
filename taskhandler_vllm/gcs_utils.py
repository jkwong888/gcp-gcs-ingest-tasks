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

def download_model_config_from_gcs(gcs_model_path: str, local_dest_dir: str) -> None:
    """
    Downloads all non-weight configuration, tokenizer, and metadata files
    from a GCS model directory to a local destination directory.
    Excludes large model weight files (safetensors, bin, pt, etc.) to keep it fast.
    """
    import os
    
    bucket_name, prefix = parse_bucket_path(gcs_model_path)
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    
    # List all blobs under the model prefix
    logger.info(f"Listing configuration files in GCS model directory: gs://{bucket_name}/{prefix}...")
    blobs = client.list_blobs(bucket, prefix=prefix)
    
    # Define file extensions to exclude (large model weight files)
    weight_extensions = (".safetensors", ".bin", ".pt", ".h5", ".pth", ".ckpt", ".gguf", ".onnx")
    
    downloaded_count = 0
    for blob in blobs:
        # Get relative path of the file from the model root prefix
        rel_path = os.path.relpath(blob.name, prefix)
        
        # Skip directories (which GCS list_blobs sometimes returns as empty blobs)
        if blob.name.endswith("/"):
            continue
            
        # Exclude files that are too large (e.g. > 50 MB) or contain weight extensions
        is_weight = any(blob.name.lower().endswith(ext) for ext in weight_extensions)
        if is_weight or blob.size > 50 * 1024 * 1024:
            logger.debug(f"Skipping weight file: {rel_path} ({blob.size} bytes)")
            continue
            
        # Define local target path, creating parent directories if needed
        local_file_path = os.path.join(local_dest_dir, rel_path)
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        
        # Download the config file
        logger.info(f"Downloading config file: {rel_path} ({blob.size} bytes) -> {local_file_path}...")
        blob.download_to_filename(local_file_path)
        downloaded_count += 1
        
    logger.info(f"Successfully downloaded {downloaded_count} configuration files to {local_dest_dir}.")
