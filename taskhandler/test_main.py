import os
import io
import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from google.api_core.exceptions import NotFound

# Set env vars before importing main to avoid long startup sleep
os.environ["INIT_SLEEP_SEC"] = "0"
os.environ["HANDLE_INPUT_SLEEP_SEC"] = "0"

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

def test_health_check():
    # We need to mock storage.Client because the lifespan still runs
    with patch("main.storage.Client"):
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.text == "OK"

            response = client.post("/health")
            assert response.status_code == 200
            assert response.text == "OK"

def test_handle_b64_success():
    with patch("main.storage.Client"):
        with TestClient(app) as client:
            dummy_png = get_dummy_image_bytes("PNG")
            b64_data = base64.b64encode(dummy_png).decode("utf-8")

            payload = {
                "b64input": b64_data,
                "gcsPath": "gs://ignored/path.png",
                "jobId": "123"
            }
            response = client.post("/", json=payload)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

def test_handle_b64_invalid_image():
    with patch("main.storage.Client"):
        with TestClient(app) as client:
            b64_data = base64.b64encode(b"not-an-image").decode("utf-8")
            payload = {
                "b64input": b64_data,
                "gcsPath": "gs://ignored/path.png",
                "jobId": "123"
            }
            response = client.post("/", json=payload)
            assert response.status_code == 400
            assert "Invalid image data" in response.json()["detail"]

def test_gcs_path_success(mock_gcs):
    # Setup mocks
    mock_blob = mock_gcs["blob"]
    
    # Mock blob.reload() to succeed
    mock_blob.reload.return_value = None
    # Mock download_as_bytes to return a dummy PNG
    dummy_png = get_dummy_image_bytes("PNG", size=(100, 200))
    mock_blob.download_as_bytes.return_value = dummy_png

    # Simulate GCS state for the status JSON
    stored_status = {
        "jobId": "job-abc-123",
        "status": "QUEUED",
        "queuedAt": "2026-06-19T22:00:00Z",
        "gcsPath": "gs://my-bucket/inputs/image.png"
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
            "gcsPath": "gs://my-bucket/inputs/image.png",
            "jobId": "job-abc-123"
        }
        response = client.post("/", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Verify GCS interactions
        mock_gcs["client"].bucket.assert_called_with("my-bucket")
        mock_gcs["bucket"].blob.assert_any_call("inputs/image.png")
        mock_gcs["bucket"].blob.assert_any_call("results/job-abc-123.json")
        
        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2

        # First upload: RUNNING
        running_data = json.loads(upload_calls[0].kwargs["data"])
        assert running_data["jobId"] == "job-abc-123"
        assert running_data["status"] == "RUNNING"
        assert running_data["gcsPath"] == "gs://my-bucket/inputs/image.png"
        assert running_data["thumbnailPath"] == "gs://my-bucket/thumbs/job-abc-123.png"
        assert running_data["queuedAt"] == "2026-06-19T22:00:00Z"  # Preserved
        assert "startedAt" in running_data  # Added
        
        # Verify attempt array structure
        assert "attempts" in running_data
        assert len(running_data["attempts"]) == 1
        attempt = running_data["attempts"][0]
        assert attempt["attemptNumber"] == 1
        assert attempt["status"] == "RUNNING"
        assert attempt["gcsPath"] == "gs://my-bucket/inputs/image.png"
        assert attempt["thumbnailPath"] == "gs://my-bucket/thumbs/job-abc-123.png"
        assert "startedAt" in attempt

        # Second upload: COMPLETED
        completed_data = json.loads(upload_calls[1].kwargs["data"])
        assert completed_data["jobId"] == "job-abc-123"
        assert completed_data["status"] == "COMPLETED"
        assert completed_data["width"] == 100
        assert completed_data["height"] == 200
        assert completed_data["format"] == "png"
        assert completed_data["thumbnailPath"] == "gs://my-bucket/thumbs/job-abc-123.png"
        assert completed_data["queuedAt"] == "2026-06-19T22:00:00Z"  # Preserved
        assert "startedAt" in completed_data  # Preserved
        assert "completedAt" in completed_data  # Added

        # Verify attempt completion
        assert "attempts" in completed_data
        assert len(completed_data["attempts"]) == 1
        completed_attempt = completed_data["attempts"][0]
        assert completed_attempt["attemptNumber"] == 1
        assert completed_attempt["status"] == "COMPLETED"
        assert "completedAt" in completed_attempt
        assert completed_attempt["result"]["width"] == 100
        assert completed_attempt["result"]["height"] == 200
        assert completed_attempt["result"]["format"] == "png"

def test_gcs_path_with_cloud_tasks_headers(mock_gcs):
    mock_blob = mock_gcs["blob"]
    mock_blob.reload.return_value = None
    dummy_png = get_dummy_image_bytes("PNG")
    mock_blob.download_as_bytes.return_value = dummy_png
    
    stored_status = {}
    mock_blob.download_as_text.side_effect = lambda: json.dumps(stored_status)
    mock_blob.upload_from_string.side_effect = lambda data, content_type=None: None
    
    with TestClient(app) as client:
        payload = {
            "gcsPath": "gs://my-bucket/inputs/image.png",
            "jobId": "job-abc-123"
        }
        headers = {
            "X-CloudTasks-TaskName": "task-abc",
            "X-CloudTasks-TaskRetryCount": "2",
            "X-CloudTasks-TaskExecutionCount": "1"
        }
        response = client.post("/", json=payload, headers=headers)
        assert response.status_code == 200
        
        # Verify first upload (RUNNING) contains the Cloud Tasks headers in the attempt
        upload_calls = mock_blob.upload_from_string.call_args_list
        running_data = json.loads(upload_calls[0].kwargs["data"])
        attempt = running_data["attempts"][0]
        assert attempt["cloudTasksTaskName"] == "task-abc"
        assert attempt["cloudTasksRetryCount"] == "2"
        assert attempt["cloudTasksExecutionCount"] == "1"

def test_gcs_path_missing_job_id():
    with patch("main.storage.Client"):
        with TestClient(app) as client:
            payload = {
                "gcsPath": "gs://my-bucket/image.png"
            }
            response = client.post("/", json=payload)
            assert response.status_code == 400
            assert "jobId is required" in response.json()["detail"]

def test_gcs_path_invalid_gcs_uri():
    with patch("main.storage.Client"):
        with TestClient(app) as client:
            payload = {
                "gcsPath": "http://not-gcs/image.png",
                "jobId": "123"
            }
            response = client.post("/", json=payload)
            assert response.status_code == 400
            assert "invalid GCS location" in response.json()["detail"]

def test_gcs_path_file_not_found(mock_gcs):
    # Mock blob.reload() to raise NotFound
    mock_blob = mock_gcs["blob"]
    mock_blob.reload.side_effect = NotFound("Object not found")

    # Simulate GCS state to link GCS reads and writes
    stored_status = {}

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
        assert response.status_code == 404
        assert "Object not found" in response.json()["detail"]

        # Verify status updates: RUNNING followed by FAILED
        upload_calls = mock_blob.upload_from_string.call_args_list
        assert len(upload_calls) == 2
        
        # Second upload should be FAILED
        failed_data = json.loads(upload_calls[1].kwargs["data"])
        assert failed_data["jobId"] == "job-missing"
        assert failed_data["status"] == "FAILED"
        assert "Object not found" in failed_data["error"]
        
        # Verify attempt failure recording
        assert "attempts" in failed_data
        assert len(failed_data["attempts"]) == 1
        failed_attempt = failed_data["attempts"][0]
        assert failed_attempt["status"] == "FAILED"
        assert "Object not found" in failed_attempt["error"]
