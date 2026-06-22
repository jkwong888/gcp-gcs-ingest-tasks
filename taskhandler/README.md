# Task Handler Service (Python FastAPI)

This service is a Python-based rewrite of the original Go task handler. It accepts task payloads, simulates processing delays, and integrates with Google Cloud Storage (GCS) to update job statuses and extract image metadata.

## Architecture & Features

- **Framework**: FastAPI running on Uvicorn.
- **Image Processing**: Pillow (PIL) for image decoding and metadata extraction (width, height, format).
- **GCS Integration**: Communicates with Google Cloud Storage to download images and upload structured JSON status files.
- **API Compatibility**: Matches the exact JSON contract of the original Go handler using Pydantic aliases (`gcsPath`, `jobId`, etc.).
- **Startup & Latency Simulation**:
  - `INIT_SLEEP_SEC`: Simulates slow container initialization (default: `30` seconds).
  - `HANDLE_INPUT_SLEEP_SEC`: Simulates image processing work delay (default: `2` seconds).

## Local Development

We use [uv](https://github.com/astral-sh/uv) to manage the Python virtual environment and dependencies.

### Prerequisites

Ensure you have `uv` installed. If not, install it via:
```bash
curl -LsSf https://astral-sh/uv/install.sh | sh
```

### Setup Environment

1. Create a virtual environment and install dependencies:
   ```bash
   uv venv
   uv pip install --index-url https://pypi.org/simple -r requirements.txt
   ```

### Running the Service Locally

To run the FastAPI service on port `8090`:
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8090
```

To run with custom sleep configuration:
```bash
INIT_SLEEP_SEC=5 HANDLE_INPUT_SLEEP_SEC=1 uv run uvicorn main:app --host 0.0.0.0 --port 8090
```

### Running Tests

The test suite uses `pytest` and mocks the GCS client to allow running tests locally without GCP credentials:
```bash
uv run pytest test_main.py
```

## API Endpoints

### 1. Health Check
- **URL**: `/health`
- **Method**: `GET`, `POST`
- **Response**: `200 OK` (Plain text `OK`)

### 2. Process Task
- **URL**: `/`
- **Method**: `POST`
- **Payload Schema**:
  ```json
  {
    "b64input": "optional_base64_encoded_image_string",
    "gcsPath": "gs://bucket-name/path/to/image.png",
    "jobId": "uuid-string",
    "signedUrl": "optional_unused_string",
    "sessionUrl": "optional_unused_string"
  }
  ```
- **Behavior**:
  - If `b64input` is provided: Decodes base64, verifies the image, sleeps for `HANDLE_INPUT_SLEEP_SEC`, and returns `200 OK`.
  - If `b64input` is omitted:
    1. Validates `jobId` and `gcsPath`.
    2. Writes a `RUNNING` status JSON to `gs://<bucket>/results/<jobId>.json`.
    3. Sleeps for `HANDLE_INPUT_SLEEP_SEC` seconds.
    4. Downloads the image from GCS, decodes it, and extracts metadata.
    5. Writes a `COMPLETED` status JSON containing image metadata (width, height, format) to `gs://<bucket>/results/<jobId>.json`.
    6. Returns `200 OK`.
  - If any error occurs (e.g., file not found, invalid image), writes a `FAILED` status JSON containing the error message to GCS and returns an appropriate HTTP error code (400, 404, 500).
