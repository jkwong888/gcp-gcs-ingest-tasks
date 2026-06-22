import os
import sys
import io
import json
import base64
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# ==============================================================================
# 1. DYNAMIC VLLM & HF MOCK SETUP (Must run before importing main)
# ==============================================================================
class MockAsyncEngineArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockStructuredOutputsParams:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockSamplingParams:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Create mock modules and inject them into sys.modules
mock_vllm = MagicMock()
mock_vllm_engine_arg_utils = MagicMock()
mock_vllm_engine_async_llm_engine = MagicMock()
mock_vllm_sampling_params = MagicMock()

mock_vllm_engine_arg_utils.AsyncEngineArgs = MockAsyncEngineArgs
mock_vllm_sampling_params.StructuredOutputsParams = MockStructuredOutputsParams
mock_vllm_sampling_params.SamplingParams = MockSamplingParams

# Setup mock engine instance
mock_engine_instance = MagicMock()
mock_vllm_engine_async_llm_engine.AsyncLLMEngine.from_engine_args.return_value = mock_engine_instance

# Mock the generate method to behave as an async generator
async def mock_generate(prompt, sampling_params, request_id, multi_modal_data=None):
    mock_output = MagicMock()
    mock_seq_output = MagicMock()
    # Return a mock JSON string representing the output of the vision model
    mock_seq_output.text = '{"caption": "A beautiful sunset over the lake", "tags": ["sunset", "lake", "water"], "primary_color": "orange"}'
    mock_output.outputs = [mock_seq_output]
    yield mock_output

mock_engine_instance.generate = mock_generate

sys.modules['vllm'] = mock_vllm
sys.modules['vllm.engine'] = MagicMock()
sys.modules['vllm.engine.arg_utils'] = mock_vllm_engine_arg_utils
sys.modules['vllm.engine.async_llm_engine'] = mock_vllm_engine_async_llm_engine
sys.modules['vllm.sampling_params'] = mock_vllm_sampling_params

# Mock HuggingFace hub downloader
mock_hf_hub = MagicMock()
mock_hf_hub.snapshot_download.return_value = "/local/cache/path/to/model"
sys.modules['huggingface_hub'] = mock_hf_hub

# ==============================================================================
# 2. TEST ENVIRONMENT CONFIGURATION
# ==============================================================================
os.environ["INIT_SLEEP_SEC"] = "0"
os.environ["HANDLE_INPUT_SLEEP_SEC"] = "0"
os.environ["MODEL_PATH"] = "google/paligemma-3b-pt-448"

# Import main after mocks are registered
from main import app

def get_dummy_image_bytes(img_format="PNG", size=(10, 10)):
    img = Image.new("RGB", size, color="red")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format=img_format)
    return img_byte_arr.getvalue()

@pytest.fixture
def mock_gcs():
    with patch("main.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        
        yield {
            "client": mock_client,
            "bucket": mock_bucket,
            "blob": mock_blob
        }

# ==============================================================================
# 3. TEST CASES
# ==============================================================================

def test_health_check(mock_gcs):
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.text == "OK"

def test_handle_b64_success(mock_gcs):
    with TestClient(app) as client:
        dummy_png = get_dummy_image_bytes("PNG")
        b64_data = base64.b64encode(dummy_png).decode("utf-8")

        payload = {
            "b64input": b64_data,
            "jobId": "job-b64-1"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "ok"
        assert result["result"]["width"] == 10
        assert result["result"]["height"] == 10
        assert result["result"]["format"] == "png"
        assert result["result"]["llm_analysis"]["caption"] == "A beautiful sunset over the lake"
        assert result["result"]["llm_analysis"]["primary_color"] == "orange"

def test_handle_b64_invalid_image(mock_gcs):
    with TestClient(app) as client:
        b64_data = base64.b64encode(b"not-an-image-payload").decode("utf-8")
        payload = {
            "b64input": b64_data,
            "jobId": "job-b64-fail"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 400
        assert "Failed to decode or process image" in response.json()["detail"]

def test_gcs_path_success(mock_gcs):
    mock_blob = mock_gcs["blob"]
    mock_blob.reload.return_value = None
    dummy_png = get_dummy_image_bytes("PNG", size=(100, 200))
    mock_blob.download_as_bytes.return_value = dummy_png

    stored_status = {
        "jobId": "job-gcs-123",
        "status": "QUEUED",
        "queuedAt": "2026-06-19T22:00:00Z",
        "gcsPath": "gs://my-bucket/inputs/photo.png"
    }

    def mock_download_as_text():
        return json.dumps(stored_status)

    def mock_upload_from_string(data, content_type=None):
        nonlocal stored_status
        stored_status = json.loads(data)

    mock_blob.download_as_text.side_effect = mock_download_as_text
    mock_blob.upload_from_string.side_effect = mock_upload_from_string

    with TestClient(app) as client:
        payload = {
            "gcsPath": "gs://my-bucket/inputs/photo.png",
            "jobId": "job-gcs-123"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify GCS interactions
        mock_gcs["client"].bucket.assert_called_with("my-bucket")
        mock_gcs["bucket"].blob.assert_any_call("inputs/photo.png")
        mock_gcs["bucket"].blob.assert_any_call("results/job-gcs-123.json")
        
        # Inspect upload calls to verify attempts array
        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2

        # First upload: RUNNING
        running_data = json.loads(upload_calls[0].kwargs["data"])
        assert running_data["status"] == "RUNNING"
        assert len(running_data["attempts"]) == 1
        assert running_data["attempts"][0]["status"] == "RUNNING"

        # Second upload: COMPLETED
        completed_data = json.loads(upload_calls[1].kwargs["data"])
        assert completed_data["status"] == "COMPLETED"
        assert completed_data["width"] == 100
        assert completed_data["height"] == 200
        assert completed_data["format"] == "png"
        assert completed_data["attempts"][0]["status"] == "COMPLETED"
        assert completed_data["attempts"][0]["result"]["llm_analysis"]["caption"] == "A beautiful sunset over the lake"

def test_gcs_path_retry_history(mock_gcs):
    mock_blob = mock_gcs["blob"]
    mock_blob.reload.return_value = None
    dummy_png = get_dummy_image_bytes("PNG", size=(150, 150))
    mock_blob.download_as_bytes.return_value = dummy_png

    stored_status = {
        "jobId": "job-gcs-retry",
        "status": "FAILED",
        "gcsPath": "gs://my-bucket/inputs/photo.png",
        "error": "Failed to load input image: Object not found",
        "attempts": [
            {
                "attemptNumber": 1,
                "status": "FAILED",
                "startedAt": "2026-06-19T22:00:00Z",
                "failedAt": "2026-06-19T22:01:00Z",
                "error": "Failed to load input image: Object not found"
            }
        ]
    }

    def mock_download_as_text():
        return json.dumps(stored_status)

    def mock_upload_from_string(data, content_type=None):
        nonlocal stored_status
        stored_status = json.loads(data)

    mock_blob.download_as_text.side_effect = mock_download_as_text
    mock_blob.upload_from_string.side_effect = mock_upload_from_string

    with TestClient(app) as client:
        payload = {
            "gcsPath": "gs://my-bucket/inputs/photo.png",
            "jobId": "job-gcs-retry"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 200

        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2

        completed_data = json.loads(upload_calls[1].kwargs["data"])
        assert completed_data["status"] == "COMPLETED"
        
        attempts = completed_data["attempts"]
        assert len(attempts) == 2
        
        # Attempt 1 FAILED
        assert attempts[0]["attemptNumber"] == 1
        assert attempts[0]["status"] == "FAILED"
        assert "Object not found" in attempts[0]["error"]
        
        # Attempt 2 COMPLETED
        assert attempts[1]["attemptNumber"] == 2
        assert attempts[1]["status"] == "COMPLETED"
        assert attempts[1]["result"]["width"] == 150
        assert attempts[1]["result"]["llm_analysis"]["caption"] == "A beautiful sunset over the lake"

def test_gcs_path_with_cloud_tasks_headers(mock_gcs):
    """
    Verifies that when Cloud Tasks headers are passed, they are successfully extracted 
    and saved inside the GCS attempt history block.
    """
    mock_blob = mock_gcs["blob"]
    mock_blob.reload.return_value = None
    dummy_png = get_dummy_image_bytes("PNG", size=(120, 240))
    mock_blob.download_as_bytes.return_value = dummy_png

    stored_status = {
        "jobId": "job-ct-headers",
        "status": "QUEUED",
        "queuedAt": "2026-06-19T22:00:00Z",
        "gcsPath": "gs://my-bucket/inputs/photo.png"
    }

    def mock_download_as_text():
        return json.dumps(stored_status)

    def mock_upload_from_string(data, content_type=None):
        nonlocal stored_status
        stored_status = json.loads(data)

    mock_blob.download_as_text.side_effect = mock_download_as_text
    mock_blob.upload_from_string.side_effect = mock_upload_from_string

    # Standard Cloud Tasks HTTP headers
    headers = {
        "X-CloudTasks-TaskName": "projects/my-proj/locations/us-central1/queues/my-q/tasks/task-xyz-777",
        "X-CloudTasks-TaskRetryCount": "2",
        "X-CloudTasks-TaskExecutionCount": "3"
    }

    with TestClient(app) as client:
        payload = {
            "gcsPath": "gs://my-bucket/inputs/photo.png",
            "jobId": "job-ct-headers"
        }
        response = client.post("/", json=payload, headers=headers)
        assert response.status_code == 200

        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2

        # Check running attempt
        running_data = json.loads(upload_calls[0].kwargs["data"])
        assert len(running_data["attempts"]) == 1
        running_attempt = running_data["attempts"][0]
        assert running_attempt["cloudTasksTaskName"] == headers["X-CloudTasks-TaskName"]
        assert running_attempt["cloudTasksRetryCount"] == headers["X-CloudTasks-TaskRetryCount"]
        assert running_attempt["cloudTasksExecutionCount"] == headers["X-CloudTasks-TaskExecutionCount"]

        # Check completed attempt
        completed_data = json.loads(upload_calls[1].kwargs["data"])
        assert len(completed_data["attempts"]) == 1
        completed_attempt = completed_data["attempts"][0]
        assert completed_attempt["cloudTasksTaskName"] == headers["X-CloudTasks-TaskName"]
        assert completed_attempt["cloudTasksRetryCount"] == headers["X-CloudTasks-TaskRetryCount"]
        assert completed_attempt["cloudTasksExecutionCount"] == headers["X-CloudTasks-TaskExecutionCount"]

def test_gcs_path_file_not_found(mock_gcs):
    from google.api_core.exceptions import NotFound
    
    mock_blob = mock_gcs["blob"]
    mock_blob.download_as_bytes.side_effect = NotFound("Object not found")

    stored_status = {
        "jobId": "job-missing",
        "status": "QUEUED",
        "queuedAt": "2026-06-19T22:00:00Z",
        "gcsPath": "gs://my-bucket/missing.png"
    }

    def mock_download_as_text():
        return json.dumps(stored_status)

    def mock_upload_from_string(data, content_type=None):
        nonlocal stored_status
        stored_status = json.loads(data)

    mock_blob.download_as_text.side_effect = mock_download_as_text
    mock_blob.upload_from_string.side_effect = mock_upload_from_string

    with TestClient(app) as client:
        payload = {
            "gcsPath": "gs://my-bucket/missing.png",
            "jobId": "job-missing"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 400
        assert "Failed to load input image" in response.json()["detail"]

        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2
        
        failed_data = json.loads(upload_calls[1].kwargs["data"])
        assert failed_data["status"] == "FAILED"
        assert len(failed_data["attempts"]) == 1
        assert failed_data["attempts"][0]["status"] == "FAILED"
        assert "Object not found" in failed_data["attempts"][0]["error"]
        assert "Object not found" in failed_data["error"]

def test_startup_fails_without_model_path():
    # Remove MODEL_PATH from env temporarily
    old_model_path = os.environ.get("MODEL_PATH")
    if "MODEL_PATH" in os.environ:
        del os.environ["MODEL_PATH"]
        
    try:
        # FastAPI TestClient will trigger lifespan and raise the startup exception
        with pytest.raises(ValueError) as exc_info:
            with TestClient(app) as _:
                pass
        assert "MODEL_PATH environment variable is required" in str(exc_info.value)
    finally:
        # Restore environment variable
        if old_model_path:
            os.environ["MODEL_PATH"] = old_model_path
