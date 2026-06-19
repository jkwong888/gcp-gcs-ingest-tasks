import { FastifyInstance } from 'fastify';
import { FromSchema } from 'json-schema-to-ts';
import util from 'util';
import { pipeline } from 'stream';
import mime from 'mime-types';
import { v4 as uuidv4 } from 'uuid';
import { uploadBody } from '../models/upload';
import { generateV4UploadSignedUrl } from '../utils/gcp';
import { storage, bucketName, bucketPrefix } from '../config';

const pump = util.promisify(pipeline);

export async function uploadRoutes(fastify: FastifyInstance) {
  /* accept a single multi-part file upload, stream it into storage
     use curl -F '<filename>=@/path/to/file' <url> to upload a file
  */
  fastify.post(
    '/upload',
    async function (req, reply) {
      const data = await req.file();

      if (data === undefined) {
        reply.code(400).send({ error: 'No file provided' });
        return;
      }

      // Verify MIME type is image
      if (!data.mimetype.startsWith('image/')) {
        reply.code(400).send({ error: 'Uploaded file must be of MIME type image/*' });
        return;
      }

      const taskId = uuidv4();
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${data.filename}`;
      req.log.info(`Uploading file: ${data.filename} with taskId: ${taskId} to location: ${gcsLocation}`);

      // Generate a stream from the body, writing metadata
      const storedFile = storage.bucket(bucketName).file(`${bucketPrefix}/${data.filename}`);
      await pump(
        data.file,
        storedFile.createWriteStream({
          metadata: {
            contentType: data.mimetype,
            metadata: {
              taskId: taskId,
            },
          },
        })
      );

      const response = {
        taskId: taskId,
        gcsPath: gcsLocation,
      };

      reply.status(201).send(response);
    }
  );

  /* create a signed URL for client to upload file themselves.
   * bucket will publish a notification that calls us later when the file is uploaded.
  */
  fastify.post<{
    Body: FromSchema<typeof uploadBody>;
  }>(
    '/uploadSignedUrl',
    {
      schema: {
        body: uploadBody,
      },
    },
    async (request, reply): Promise<void> => {
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${request.body.filename}`;
      const expectedContentType = request.body.contentType || mime.lookup(request.body.filename) || 'application/octet-stream';
      
      // Verify expected MIME type is image
      if (!expectedContentType.startsWith('image/')) {
        reply.code(400).send({ error: 'File content type must be of type image/*' });
        return;
      }

      const taskId = uuidv4();
      request.log.info(`Generating signed URL for file: ${request.body.filename} with taskId: ${taskId} to location: ${gcsLocation}`);

      const url = await generateV4UploadSignedUrl(
        request.body.filename,
        'write' as const,
        expectedContentType,
        taskId
      );
      reply.header("Location", url);

      const response = {
        taskId: taskId,
        gcsPath: gcsLocation,
        signedUrl: url,
        expectedContentType: expectedContentType,
      };

      reply.status(201).send(response);
    }
  );

  fastify.post<{
    Body: FromSchema<typeof uploadBody>;
  }>(
    '/uploadResumable',
    {
      schema: {
        body: uploadBody,
      },
    },
    async (request, reply): Promise<void> => {
      const gcsLocation = `gs://${bucketName}/${bucketPrefix}/${request.body.filename}`;
      const expectedContentType = request.body.contentType || mime.lookup(request.body.filename) || 'application/octet-stream';

      // Verify expected MIME type is image
      if (!expectedContentType.startsWith('image/')) {
        reply.code(400).send({ error: 'File content type must be of type image/*' });
        return;
      }

      const taskId = uuidv4();
      request.log.info(`Generating resumable link for file: ${request.body.filename} with taskId: ${taskId} to location: ${gcsLocation}`);

      const url = await generateV4UploadSignedUrl(
        request.body.filename,
        'resumable' as const,
        expectedContentType,
        taskId
      );
      reply.header("Location", url);

      const response = {
        taskId: taskId,
        gcsPath: gcsLocation,
        sessionUrl: url,
      };

      reply.status(201).send(response);
    }
  );
}
