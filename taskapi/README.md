# task API

## environment variables:

```
BUCKET_NAME       # name of bucket to upload files to
BUCKET_PREFIX     # prefix of files in the bucket (defaults to 'input')
QUEUE_NAME        # name of cloud tasks queue
PROJECT_ID        # project id where the cloud tasks queue is located
REGION            # region where the cloud tasks queue is located
TASK_HANDLER_URL  # url of the task handler to call after files are uploaded
TASKS_SERVICE_ACCOUNT_EMAIL   # service account email representing the tasks (will be used to trigger the task handler url)
STORAGE_SERVICE_ACCOUNT_EMAIL # service account email representing the storage notification (notifications will have a token containing this identity)
```

## deploy steps

1. Build image and deploy to Cloud Run
2. Create a pubsub subscription on the storage notification topic and set it to `https://<cloud run url>/uploadNotification`. Make sure the subscription uses the account in `${STORAGE_SERVICE_ACCOUNT_EMAIL}`.
3. Upload a file:

   - **Web UI**: Open your browser and navigate to `https://<cloud run URL>/` to access the interactive dashboard.
   
   - `POST /upload` to upload a file synchronously (using multipart upload):
     ```
     curl -F 'file=@/path/to/image.png' <cloud run URL>/upload
     ```
     *Note: The API only accepts files of MIME type `image/*`.*

   - `POST /uploadSignedUrl` to get a signed URL to upload a single file to:
     ```
     curl -i -X POST -H "Content-Type: application/json" -d '{"filename":"image.png"}' <cloud run URL>/uploadSignedUrl
     ```
     Will return a URL in the location header (as well as a JSON response containing the URL), then upload the file including the `x-goog-meta-taskid` header:
     ```
     curl -X PUT --upload-file /path/to/image.png -H "Content-Type: image/png" -H "x-goog-meta-taskid: <taskId_returned_in_json>" '<signed URL>'
     ```

   - `POST /uploadResumable` to get a resumable session URL to upload a file:
     ```
     curl -i -X POST -H "Content-Type: application/json" -d '{"filename":"image.png"}' <cloud run URL>/uploadResumable
     ```
     Will return a session URL in the body. Start the upload session, ensuring the `x-goog-meta-taskid` is sent:
     ```
     curl -i -X POST -H "x-goog-resumable: start" -H "x-goog-meta-taskid: <taskId>" <sessionUrl>
     ```
     Will return a signed URL in the `Location` header, which you can use to PUT your file.

4. **Task Progress & Dashboard API**:
   - `GET /api/tasks`: Returns all tasks, statuses (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `PENDING`), and short-lived read signed URLs for original images and thumbnails.
   - `DELETE /api/tasks/:taskId`: Deletes the input image, the result JSON, and the thumbnail from GCS.

---

## Code Structure

The codebase is organized into a modular TypeScript structure:

```
taskapi/
├── dist/                     # Compiled JavaScript output (production)
├── public/
│   └── index.html            # Web Dashboard Frontend (Tailwind, HTML, JS)
├── src/
│   ├── config.ts             # Environment variables and initialized GCP clients
│   ├── index.ts              # Entrypoint (defines Fastify app factory & serves static public/)
│   ├── middleware/
│   │   └── auth.ts           # Authentication middleware (PubSub token validation)
│   ├── models/
│   │   ├── notification.ts   # PubSub notification JSON schemas & types
│   │   ├── task.ts           # Cloud Tasks JSON schemas & types
│   │   └── upload.ts         # File upload JSON schemas & types
│   ├── routes/
│   │   ├── notification.ts   # POST /uploadNotification router
│   │   ├── ping.ts           # GET /ping router
│   │   ├── tasks.ts          # GET /api/tasks, DELETE /api/tasks/:taskId routers
│   │   └── upload.ts         # POST /upload, /uploadSignedUrl, /uploadResumable routers
│   └── utils/
│       └── gcp.ts            # GCP helper utilities (signed URLs, Cloud Tasks dispatch)
├── tests/
│   ├── routes/               # Integration/unit tests for Fastify endpoints
│   │   ├── notification.test.ts
│   │   ├── ping.test.ts
│   │   ├── tasks.test.ts     # Task dashboard/deletion tests
│   │   └── upload.test.ts
│   └── setup.ts              # Global Jest setup & GCP client mocks
```

## Development & Testing

### Running Tests Locally
Ensure Node.js and NPM are installed (supported via NVM).
```bash
npm install
npm test
```

### Running Tests in Docker

You can run the unit test suite inside a Docker container without needing Node or NPM installed on your host machine.

#### 1. Run tests as part of the Docker image build:
Building the Docker image will automatically execute the entire test suite and verify that TypeScript compiles without errors.
```bash
docker build -t taskapi:test .
```

#### 2. Run tests interactively (for fast development feedback):
To run tests quickly without rebuilding the full Docker image, you can mount your workspace directory into a temporary Node container:
```bash
docker run --rm -v $(pwd):/usr/src/app -w /usr/src/app node:18 npm test
```
This command runs Jest on your local files, reflecting any edits immediately.