import { FromSchema } from 'json-schema-to-ts';
import { taskBody } from '../models/task';
import {
  taskClient,
  projectId,
  region,
  queueName,
  taskHandlerUrl,
  taskServiceAccountEmail,
  storage,
  bucketName,
  bucketPrefix,
  logger,
} from '../config';

export async function createHttpTaskWithToken(payload: FromSchema<typeof taskBody>): Promise<string|null> {
  // Construct the fully qualified queue name.
  const parent = taskClient.queuePath(projectId, region, queueName);

  const cloudTaskReq = {
    httpRequest: {
      headers: {
        'Content-Type': 'application/json',
      },
      httpMethod: 'POST' as const,
      url: taskHandlerUrl,
      oidcToken: {
        serviceAccountEmail: taskServiceAccountEmail,
      },
      body: "",
    },
  };

  if (payload) {
    cloudTaskReq.httpRequest.body = Buffer.from(JSON.stringify(payload)).toString('base64');
  }

  logger.info(`Sending task: ${JSON.stringify(cloudTaskReq)}`);
  // Send create task request.
  const request = {parent: parent, task: cloudTaskReq};
  const [response] = await taskClient.createTask(request).catch((error) => {
    throw error;
  });

  if (response.name === undefined) {
    throw new Error(`Unable to create task: task name is undefined`);
  }

  const taskName = response.name;
  return Promise.resolve(taskName);
}

export async function generateV4UploadSignedUrl(fileName: string, action: 'write' | 'resumable', contentType: string | undefined, taskId: string) {
  const options = {
    version: 'v4' as const,
    action: action,
    expires: Date.now() + 15 * 60 * 1000, // 15 minutes
    contentType: contentType || undefined,
    extensionHeaders: {
      'x-goog-meta-taskid': taskId,
    }
  };

  // Get a v4 signed URL for uploading file
  const [url] = await storage
    .bucket(bucketName)
    .file(`${bucketPrefix}/${fileName}`)
    .getSignedUrl(options)
    .catch((error) => {
      throw error;
    });

  logger.info(`Generated PUT ${action} signed URL with taskId ${taskId}: ${url}`);
  return url;
}
