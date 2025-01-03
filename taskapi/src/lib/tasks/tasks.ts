import { CloudTasksClient } from '@google-cloud/tasks';
import { TaskBody } from '../types/task';
import conf from '../conf/config';
import logger from '../log/log';

const taskClient = new CloudTasksClient();

export async function createHttpTaskWithToken(payload: TaskBody): Promise<string|null> {
    // TODO(developer): Uncomment these lines and replace with your values.
    // const project = 'my-project-id';
    // const queue = 'my-queue';
    // const location = 'us-central1';
    // const url = 'https://example.com/taskhandler';
    // const serviceAccountEmail = 'client@<project-id>.iam.gserviceaccount.com';
    // const payload = 'Hello, World!';
  
    // Construct the fully qualified queue name.
    const parent = taskClient.queuePath(conf.projectId, conf.region, conf.queueName);
  
    const cloudTaskReq = {
      httpRequest: {
        headers: {
          'Content-Type': 'application/json',
        },
        httpMethod: 'POST' as const,
        url: conf.taskHandlerUrl,
        oidcToken: {
          serviceAccountEmail: conf.taskServiceAccountEmail,
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