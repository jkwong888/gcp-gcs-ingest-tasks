import { FastifyInstance } from 'fastify';
import { FromSchema } from 'json-schema-to-ts';
import { v4 as uuidv4 } from 'uuid';
import { Jimp, JimpMime } from 'jimp';
import { pubsubUploadNotification } from '../models/notification';
import { validateIDToken } from '../middleware/auth';
import { createHttpTaskWithToken } from '../utils/gcp';
import { storage, bucketName, bucketPrefix } from '../config';

export async function notificationRoutes(fastify: FastifyInstance) {
  fastify.post<{
    Body: FromSchema<typeof pubsubUploadNotification>;
  }>(
    '/uploadNotification',
    {
      preHandler: validateIDToken,
    },
    async function (req, reply) {
      const attributes = req.body.message?.attributes;
      const objectId = attributes?.objectId;
      const bucketId = attributes?.bucketId;

      if (!objectId || !bucketId) {
        reply.status(400).send({ error: 'Missing objectId or bucketId in notification attributes' });
        return;
      }

      const gcsLocation = `gs://${bucketId}/${objectId}`;
      req.log.info(`Received upload notification: ${JSON.stringify(req.body)}, headers: ${JSON.stringify(req.headers)}`);

      if (attributes?.eventType !== "OBJECT_FINALIZE") {
        // get pubsub to shut up about this event if an object was not finalized
        reply.status(200).send();
        return;
      }

      if (bucketId !== bucketName) {
        // get pubsub to shut up about this event if it's from a bucket we don't care about
        reply.status(200).send();
        return;
      }

      if (!objectId.startsWith(bucketPrefix + '/')) {
        // get pubsub to shut up about this event if it's not the matching bucket prefix
        reply.status(200).send();
        return;
      }

      // Decode the GCS Object resource from the pubsub message data
      let taskId: string | null = null;
      if (req.body.message?.data) {
        try {
          const objectData = JSON.parse(Buffer.from(req.body.message.data, 'base64').toString('utf-8'));
          taskId = objectData.metadata?.taskId || null;
          req.log.info(`Extracted taskId: ${taskId} from object metadata`);
        } catch (e) {
          req.log.error(`Failed to parse GCS object resource from pubsub message data: ${e}`);
        }
      }

      // Fallback if taskId is not in metadata
      const jobId = taskId || uuidv4();
      req.log.info(`Processing job ${jobId} for object ${gcsLocation}`);

      const bucket = storage.bucket(bucketName);
      const originalFile = bucket.file(objectId);
      let thumbnailPath: string | null = null;

      // 1. Download original image and generate thumbnail using Jimp v1
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

        // Upload thumbnail to GCS
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
        // Log the error but don't fail the whole pipeline
        req.log.error(`Failed to generate or upload thumbnail: ${error}`);
      }

      // 2. Write the initial "QUEUED" status JSON to GCS results folder (containing thumbnail path)
      try {
        const statusFile = bucket.file(`results/${jobId}.json`);
        const statusData = {
          jobId: jobId,
          gcsPath: gcsLocation,
          status: 'QUEUED',
          thumbnailPath: thumbnailPath,
          queuedAt: new Date().toISOString(),
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

      // 3. Generate a cloud task for this file
      const taskBody = {
        jobId: jobId,
        gcsPath: gcsLocation,
      };

      let cloudTaskId: string | null = null;
      try {
        cloudTaskId = await createHttpTaskWithToken(taskBody);
      } catch (error) {
        req.log.error(`Failed to create cloud task: ${error}`);
        // If enqueuing fails, update the status file to FAILED
        try {
          const statusFile = bucket.file(`results/${jobId}.json`);
          const failedStatus = {
            jobId: jobId,
            gcsPath: gcsLocation,
            status: 'FAILED',
            thumbnailPath: thumbnailPath,
            error: `Failed to enqueue cloud task: ${error}`,
            failedAt: new Date().toISOString(),
          };
          await statusFile.save(JSON.stringify(failedStatus), { contentType: 'application/json' });
        } catch (e) {
          req.log.error(`Failed to write FAILED status to GCS: ${e}`);
        }
        reply.status(500).send(error);
        return;
      }

      const response = {
        jobId: jobId,
        taskId: cloudTaskId,
        gcsPath: gcsLocation,
        thumbnailPath: thumbnailPath,
      };
      req.log.info(`Created job task ${cloudTaskId} for object ${gcsLocation}`);

      reply.status(201).send(response);
    }
  );
}
