import fastify, { FastifyReply, FastifyRequest } from 'fastify'
import util from 'util';
import { v4 as uuidv4 } from 'uuid';
import { FromSchema } from 'json-schema-to-ts';
import { Storage } from '@google-cloud/storage';
import { CloudTasksClient } from '@google-cloud/tasks';
import { pipeline } from 'stream';
import { fastifyMultipart } from '@fastify/multipart';
import { OAuth2Client } from 'google-auth-library';
import mime from 'mime-types';
import pino from 'pino'

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

const storage = new Storage();
const taskClient = new CloudTasksClient();
const authClient = new OAuth2Client();
const pump = util.promisify(pipeline);
const logger = pino();


const server = fastify({
  logger: logger,
});

// use fastify multipart upload plugin
server.register(fastifyMultipart);

server.get('/ping', async (request, reply) => {
  return 'pong\n'
})

const uploadBody = {
    type: 'object',
    properties: {
      filename: { type: 'string' },
      contentType: { type: 'string' },
    },
    required: ["filename"],
} as const;

const taskBody = {
    type: 'object',
    properties: {
      gcsPath: { type: 'string' },
    },
    required: ["gcsPath"],
} as const;

/*
Example message:
{
  "message": {
    "attributes": {
      "bucketId": "<bucket-id>",
      "eventTime": "<time>",
      "eventType": "OBJECT_FINALIZE",
      "notificationConfig": "projects/_/buckets/<bucket/notificationConfigs/<num>",
      "objectGeneration": "<generation>",
      "objectId": "path/to/object",
      "payloadFormat": "JSON_API_V1"
    },
    "data": "<base64 encoded json message>",
    "messageId": "<id>",
    "message_id": "<id>",
    "publishTime": "<publish time>",
    "publish_time": "<publish time>"
  },
  "subscription": "projects/<project id>/subscriptions/<subscription id>"
}
 */
const pubsubUploadNotification = {
    type: 'object',
    properties: {
      message: {
        type: 'object',
        properties: {
          attributes: {
            type: 'object',
            properties: {
              bucketId: { type: 'string' },
              eventTime: { type: 'string' },
              eventType: { type: 'string' },
              notificationConfig: { type: 'string' },
              objectId: { type: 'string' },
              objectGeneration: { type: 'integer' },
              payloadFormat: { type: 'string' },
            }
          },
          data: { type: 'string' },
          messageId: { type: 'string' },
          publishTime: { type: 'string' },
        }
      },
      subscription: { type: 'string' },
    },
} as const;

async function createHttpTaskWithToken(payload: FromSchema<typeof taskBody>): Promise<string|null> {
  // TODO(developer): Uncomment these lines and replace with your values.
  // const project = 'my-project-id';
  // const queue = 'my-queue';
  // const location = 'us-central1';
  // const url = 'https://example.com/taskhandler';
  // const serviceAccountEmail = 'client@<project-id>.iam.gserviceaccount.com';
  // const payload = 'Hello, World!';

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

async function generateV4UploadSignedUrl(fileName: string, action: 'write' | 'resumable', contentType: string | undefined) {
  // These options will allow temporary uploading of the file with outgoing
  // Content-Type: application/octet-stream header.
  const options = {
    version: 'v4' as const,
    action: action,
    expires: Date.now() + 15 * 60 * 1000, // 15 minutes
    contentType: contentType || undefined,
  };

  // Get a v4 signed URL for uploading file
  const [url] = await storage
    .bucket(bucketName)
    .file(`${bucketPrefix}/${fileName}`)
    .getSignedUrl(options)
    .catch((error) => {
      throw error;
    });

  logger.info(`Generated PUT ${action} signed URL: ${url}`);
  return url;
}

async function validateIDToken(request: FastifyRequest, reply: FastifyReply): Promise<void> {
  // Verify that the push request originates from Cloud Pub/Sub.
  try {
    request.log.info(`validate auth header: ${request.headers.authorization}`);
    // Get the Cloud Pub/Sub-generated JWT in the "Authorization" header.
    const authHeader = request.headers.authorization || "";
    const [, token] = authHeader.match(/Bearer (.*)/) || [];
    if (!token) {
      reply.status(401).send();
      return;
    }

    // Verify and decode the JWT.
    // Note: For high volume push requests, it would save some network
    // overhead if you verify the tokens offline by decoding them using
    // Google's Public Cert; caching already seen tokens works best when
    // a large volume of messages have prompted a single push server to
    // handle them, in which case they would all share the same token for
    // a limited time window.
    const ticket = await authClient.verifyIdToken({
      idToken: token,
    }).catch ((error) => {
      request.log.error(`ID token verify failed: ${error}`)
      reply.status(401).send();
      return;
    });

    const claim = ticket?.getPayload();
    if (claim == undefined) {
      request.log.error(`No claims in token`);
      reply.status(401).send();
      return;
    }

    // IMPORTANT: you should validate claim details not covered
    // by signature and audience verification above, including:
    //   - Ensure that `claim.email` is equal to the expected service
    //     account set up in the push subscription settings.
    //   - Ensure that `claim.email_verified` is set to true.

    if (!claim.email_verified) {
      request.log.error(`email_verified = false`);
      reply.status(401).send();
      return;
    }

    if (claim.email != storageServiceAccountEmail) {
      request.log.error(`email in token ${claim.email} does not match expected email: ${storageServiceAccountEmail}`);
      reply.status(401).send();
      return;
    }
  } catch (e) {
    reply.status(401).send(e);
  }
}

/* accept a single multi-part file upload, stream it into storage and create a cloud task to handle it
   needs multiple instance of this API to handle multiple files, but task will be created synchronously when file upload completes
   use curl -F '<filename>=@/path/to/file' <url> to upload a file
*/
server.post(
    '/upload',
    async function (req, reply) {
      const data = await req.file()

      if (data === undefined) {
        reply.code(400);
        return;
      }
        /*
        request.body has type
        {
          [x: string]: unknown;
          description?: string;
          done?: boolean;
          name: string;
        }
        */
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${data.filename}`
      req.log.info(`uploading file: ${data.filename} to location: ${gcsLocation}`);
    
        //request.body.name // will not throw type error
        //request.body.notthere // will throw type error

      // generate a stream from the body
      const storedFile = storage.bucket(bucketName).file(`${bucketPrefix}/${data.filename}`);
      await pump(data.file, storedFile.createWriteStream());

      const response = {
        gcsPath: gcsLocation,
      }
    
      reply.status(201).send(JSON.stringify(response));
    },    
)

/* create a signed URL for client to upload file themselves.  
 * bucket will publish a notification that calls us later when the file is uploaded.
 * TODO: probably want to have some kind of cache here to keep track of which uploads are initiated by our API, or tighten up the 
 * security on the bucket so nobody can upload except through our API
*/
server.post<{ 
  Body: FromSchema<typeof uploadBody> 
}>(
    '/uploadSignedUrl',
    {
        schema: {
            body: uploadBody,
            response: {
                201: {
                    type: 'string',
                },
            },
        },

    },
    async (request, reply): Promise<void> => {

        /*
        request.body has type
        {
          [x: string]: unknown;
          description?: string;
          done?: boolean;
          name: string;
        }
        */
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${request.body.filename}`
      const expectedContentType = request.body.contentType || mime.lookup(request.body.filename) || 'application/octet-stream' ;
      request.log.info(`uploading file: ${request.body.filename} to location: ${gcsLocation}, expected Content-Type: ${expectedContentType}`);
    
        //request.body.name // will not throw type error
        //request.body.notthere // will throw type error

      const url = await generateV4UploadSignedUrl(
        request.body.filename, 
        'write' as const,
        expectedContentType);
      reply.header("Location", url);

      const response = {
        gcsPath: gcsLocation,
        signedUrl: url,
        expectedContentType: expectedContentType,
      }
    
      reply.status(201).send(JSON.stringify(response));
    },    
);


server.post<{ 
  Body: FromSchema<typeof uploadBody> 
}>(
    '/uploadResumable',
    {
        schema: {
            body: uploadBody,
            response: {
                201: {
                    type: 'string',
                },
            },
        },

    },
    async (request, reply): Promise<void> => {

        /*
        request.body has type
        {
          [x: string]: unknown;
          description?: string;
          done?: boolean;
          name: string;
        }
        */
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${request.body.filename}`
      request.log.info(`generating link for file(s): ${request.body.filename} to location: ${gcsLocation}`);
   
        //request.body.name // will not throw type error
        //request.body.notthere // will throw type error

      const url = await generateV4UploadSignedUrl(
        request.body.filename, 
        'resumable' as const,
        undefined);
      reply.header("Location", url);

      // generate a cloud task for this file -- the task can check the sessionUrl for the upload progress
      const response = {
        gcsPath: gcsLocation,
        sessionUrl: url,
      }

      reply.status(201).send(JSON.stringify(response));
    },    
);

server.post<{ 
  Body: FromSchema<typeof pubsubUploadNotification> 
}>(
    '/uploadNotification',
    {
      preHandler: validateIDToken,
    },
    async function (req, reply) {
      // TODO: validate that this notification came from pubsub, using the storage SA.


      const gcsLocation = `gs://${req.body.message?.attributes?.bucketId}/${req.body.message?.attributes?.objectId}`
      req.log.info(`Received upload notification: ${JSON.stringify(req.body)}, headers: ${JSON.stringify(req.headers)}`);

      if (req.body.message?.attributes?.eventType != "OBJECT_FINALIZE") {
        // get pubsub to shut up about this event if an object was not finalized
        reply.status(200).send();
        return;
      }

      if (req.body.message?.attributes?.bucketId != bucketName) {
        // get pubsub to shut up about this event if it's from a bucket we don't care about
        reply.status(200).send();
        return;
      }

      if (!req.body.message?.attributes?.objectId?.startsWith(bucketPrefix)) {
        // get pubsub to shut up about this event if it's not the matching bucket prefix
        reply.status(200).send();
        return;
      }
    
      const jobId = uuidv4();
      const taskBody = {
        jobId: jobId,
        gcsPath: gcsLocation,
      }
      req.log.info(`Creating job ${jobId} for object ${gcsLocation}`);

      // generate a cloud task for this file
      const taskId = await createHttpTaskWithToken(taskBody).catch((error) => {
        reply.status(500).send(error);
        return;
      });

      const response = {
        jobId: jobId,
        taskId: taskId,
        gcsPath: gcsLocation,
      }
      req.log.info(`Created job task ${taskId} for object ${gcsLocation}`);
    
      reply.status(201).send();
    },    
)

server.listen({ 
  host: '0.0.0.0', 
  port: 8000 }, 
  (err, address) => {
  if (err) {
    logger.error(err)
    process.exit(1)
  }
  logger.info(`Server listening at ${address}`)
})