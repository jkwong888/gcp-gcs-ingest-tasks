import { Storage } from '@google-cloud/storage';
import { CloudTasksClient } from '@google-cloud/tasks';
import { OAuth2Client } from 'google-auth-library';
import pino from 'pino';

export const bucketName = process.env.BUCKET_NAME || "";
export const bucketPrefix = process.env.BUCKET_PREFIX || "input";
export const queueName = process.env.QUEUE_NAME || "";
export const projectId = process.env.PROJECT_ID || "";
export const region = process.env.REGION || "";
export const taskHandlerUrl = process.env.TASK_HANDLER_URL || "";

// the SA the cloud tasks queue uses to trigger the Cloud Run task handler
export const taskServiceAccountEmail = process.env.TASKS_SERVICE_ACCOUNT_EMAIL || "";

// the SA that pubsub uses to send us notifications
export const storageServiceAccountEmail = process.env.STORAGE_SERVICE_ACCOUNT_EMAIL || "";

export const storage = new Storage();
export const taskClient = new CloudTasksClient();
export const authClient = new OAuth2Client();
export const logger = pino();

if (!storageServiceAccountEmail) {
  logger.warn("STORAGE_SERVICE_ACCOUNT_EMAIL is not set. Ingestion notifications will not be validated in production.");
}
