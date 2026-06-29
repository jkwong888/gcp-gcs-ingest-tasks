import fastify from 'fastify';
import { Storage } from '@google-cloud/storage';
import { CloudTasksClient } from '@google-cloud/tasks';
import { Jimp, JimpMime } from 'jimp';
import { v4 as uuidv4 } from 'uuid';

// 1. Read and validate environment variables
const projectId = process.env.PROJECT_ID;
const region = process.env.REGION;
const queueName = process.env.QUEUE_NAME;
const taskHandlerUrl = process.env.TASK_HANDLER_URL;
const taskServiceAccountEmail = process.env.TASKS_SERVICE_ACCOUNT_EMAIL;
const bucketName = process.env.BUCKET_NAME;
const bucketPrefix = 'input'; // GCS folder prefix to monitor

if (!projectId || !region || !queueName || !taskHandlerUrl || !taskServiceAccountEmail || !bucketName) {
  console.error('CRITICAL ERROR: Missing required environment variables!');
  process.exit(1);
}

// 2. Initialize Google Cloud SDK clients
const storageClient = new Storage({ projectId });
const taskClient = new CloudTasksClient();

// 3. Initialize Fastify server
const app = fastify({
  logger: true, // Uses Fastify's native Pino logger
});

// TypeScript interface for Pub/Sub push notification payload
interface PubSubMessage {
  message?: {
    attributes?: {
      bucketId?: string;
      objectId?: string;
      eventType?: string;
    };
    data?: string;
    messageId?: string;
  };
}

// 4. Register the /uploadNotification endpoint
app.post('/uploadNotification', async (req, reply) => {
  const body = req.body as PubSubMessage;
  const attributes = body.message?.attributes;
  const objectId = attributes?.objectId;
  const bucketId = attributes?.bucketId;

  // Basic validation: ensure we have bucket and object metadata
  if (!objectId || !bucketId) {
    reply.status(400).send({ error: 'Missing objectId or bucketId in notification attributes' });
    return;
  }

  const gcsLocation = `gs://${bucketId}/${objectId}`;
  req.log.info(`Received GCS upload notification for: ${gcsLocation}`);

  // Ignore events that are not object creation (e.g. metadata updates)
  if (attributes?.eventType !== 'OBJECT_FINALIZE') {
    req.log.info(`Ignoring non-OBJECT_FINALIZE event: ${attributes?.eventType}`);
    reply.status(200).send();
    return;
  }

  // Ignore events from other buckets
  if (bucketId !== bucketName) {
    req.log.info(`Ignoring event from unexpected bucket: ${bucketId}`);
    reply.status(200).send();
    return;
  }

  // Ignore events outside the target prefix folder
  if (!objectId.startsWith(bucketPrefix + '/')) {
    req.log.info(`Ignoring event outside target folder prefix: ${objectId}`);
    reply.status(200).send();
    return;
  }

  // Extract custom taskId from GCS metadata if present (provided by custom uploads)
  let taskId: string | null = null;
  if (body.message?.data) {
    try {
      const objectData = JSON.parse(Buffer.from(body.message.data, 'base64').toString('utf-8'));
      taskId = objectData.metadata?.taskId || null;
      req.log.info(`Extracted taskId: ${taskId} from object metadata`);
    } catch (e) {
      req.log.error(`Failed to parse GCS object resource from pubsub message data: ${e}`);
    }
  }

  // Generate a unique Job ID (fallback to UUID if no taskId was passed)
  const jobId = taskId || uuidv4();
  req.log.info(`Assigned Job ID ${jobId} to process ${gcsLocation}`);

  const bucket = storageClient.bucket(bucketName);
  const originalFile = bucket.file(objectId);
  let thumbnailPath: string | null = null;

  // STEP A: Download original image and generate thumbnail using Jimp
  try {
    req.log.info(`Downloading original image for thumbnailing: ${objectId}`);
    const [imageBuffer] = await originalFile.download();
    
    req.log.info(`Decoding image using Jimp...`);
    const image = await Jimp.read(imageBuffer);
    
    // Calculate aspect ratio resizing within a 128x128 bounding box
    const width = image.bitmap.width;
    const height = image.bitmap.height;
    let thumbW = 128;
    let thumbH = 128;
    if (width > height) {
      thumbH = Math.round(height * 128 / width);
    } else {
      thumbW = Math.round(width * 128 / height);
    }

    req.log.info(`Resizing image to thumbnail: ${thumbW}x${thumbH}...`);
    image.resize({ w: thumbW, h: thumbH });
    
    req.log.info(`Encoding thumbnail to PNG buffer...`);
    const thumbBuffer = await image.getBuffer(JimpMime.png);

    // Upload thumbnail to GCS thumbs/ folder
    const thumbObjPath = `thumbs/${jobId}.png`;
    const thumbFile = bucket.file(thumbObjPath);
    req.log.info(`Uploading thumbnail to GCS: ${thumbObjPath}`);
    await thumbFile.save(thumbBuffer, {
      contentType: 'image/png',
      resumable: false,
    });

    thumbnailPath = `gs://${bucketName}/${thumbObjPath}`;
    req.log.info(`Successfully generated and uploaded thumbnail to ${thumbnailPath}`);
  } catch (error) {
    // Log GCS/Jimp errors but do not crash the pipeline; try to proceed with enqueuing
    req.log.error(`Failed to generate or upload thumbnail: ${error}`);
  }

  const queuedAt = new Date().toISOString();

  // STEP B: Write initial "QUEUED" status JSON to GCS results/ folder
  try {
    const statusFile = bucket.file(`results/${jobId}.json`);
    const statusData = {
      jobId: jobId,
      gcsPath: gcsLocation,
      status: 'QUEUED',
      thumbnailPath: thumbnailPath,
      queuedAt: queuedAt,
    };
    await statusFile.save(JSON.stringify(statusData), {
      contentType: 'application/json',
      resumable: false,
    });
    req.log.info(`Saved initial QUEUED status to results/${jobId}.json`);
  } catch (error) {
    req.log.error(`Failed to write QUEUED status to GCS: ${error}`);
    reply.status(500).send({ error: 'Failed to write initial task status' });
    return;
  }

  // STEP C: Enqueue the task to Cloud Tasks
  const taskBody = {
    jobId: jobId,
    gcsPath: gcsLocation,
  };

  let cloudTaskId: string | null = null;
  try {
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
        body: Buffer.from(JSON.stringify(taskBody)).toString('base64'),
      },
    };

    req.log.info(`Enqueuing Cloud Task: ${JSON.stringify(cloudTaskReq)}`);
    const [response] = await taskClient.createTask({ parent, task: cloudTaskReq });
    cloudTaskId = response.name || null;
  } catch (error) {
    req.log.error(`Failed to create Cloud Task: ${error}`);
    
    // Self-healing: If enqueuing fails, overwrite the status file to FAILED
    try {
      const statusFile = bucket.file(`results/${jobId}.json`);
      const failedStatus = {
        jobId: jobId,
        gcsPath: gcsLocation,
        status: 'FAILED',
        thumbnailPath: thumbnailPath,
        error: `Failed to enqueue cloud task: ${error}`,
        queuedAt: queuedAt,
        failedAt: new Date().toISOString(),
      };
      await statusFile.save(JSON.stringify(failedStatus), { contentType: 'application/json' });
    } catch (e) {
      req.log.error(`Failed to write FAILED status update to GCS: ${e}`);
    }
    reply.status(500).send(error);
    return;
  }

  // Return success response to Pub/Sub to acknowledge delivery
  const response = {
    jobId: jobId,
    taskId: cloudTaskId,
    gcsPath: gcsLocation,
    thumbnailPath: thumbnailPath,
  };
  req.log.info(`Successfully created job task ${cloudTaskId} for object ${gcsLocation}`);
  reply.status(201).send(response);
});

// 5. Start the Fastify server
const port = process.env.PORT ? parseInt(process.env.PORT) : 8000;
const host = '0.0.0.0';

app.listen({ host, port }, (err, address) => {
  if (err) {
    app.log.error(err);
    process.exit(1);
  }
  app.log.info(`Server listening at ${address}`);
});
