import { Config } from "../types/config";

const bucketName = process.env.BUCKET_NAME || "";
const bucketPrefix = process.env.BUCKET_PREFIX || "upload";
const queueName = process.env.QUEUE_NAME || "";
const projectId = process.env.PROJECT_ID || "";
const region = process.env.REGION || "";
const taskHandlerUrl = process.env.TASK_HANDLER_URL || "";

// the SA the cloud tasks queue uses to trigger the Cloud Run task handler
const taskServiceAccountEmail = process.env.TASKS_SERVICE_ACCOUNT_EMAIL || "";

// the SA that pubsub uses to send us notifications
const storageServiceAccountEmail = process.env.STORAGE_SERVICE_ACCOUNT_EMAIL || "";

export const conf: Config = {
  bucketName,
  bucketPrefix,
  projectId,
  queueName,
  region,
  taskHandlerUrl,
  storageServiceAccountEmail,
  taskServiceAccountEmail,
}

export default conf;