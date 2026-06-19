# Cloud Run based ingest process

## Architecture Diagram

![architecture diagram](./images/gcs-task-ingestion.png)


## Instructions

We provide separate, self-contained deployment scripts in each directory to automate building and deploying the services to Cloud Run.

For detailed setup, configuration, and execution instructions, please refer to the [DEPLOYMENT.md](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/DEPLOYMENT.md) guide.

1. **Configure Infrastructure**: Provision the bucket, queue, and service accounts using Terraform in `terraform/`.
2. **Deploy Task Handler**: Update the configuration at the top of [taskhandler/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskhandler/deploy.sh) and run it from the `taskhandler/` directory.
3. **Deploy Task API**: Update the configuration at the top of [taskapi/deploy.sh](file:///usr/local/google/home/jkwng/code/gcp-gcs-ingest-tasks/taskapi/deploy.sh) and run it from the `taskapi/` directory. (It will auto-detect the Task Handler URL if left blank).
4. **Test**: Use the interactive dashboard or run the code in `taskgen` to upload an image to GCS and watch it process.

