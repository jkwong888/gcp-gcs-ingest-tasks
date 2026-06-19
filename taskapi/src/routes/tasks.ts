import { FastifyInstance } from 'fastify';
import { storage, bucketName, bucketPrefix } from '../config';

export async function taskRoutes(fastify: FastifyInstance) {
  // GET /api/tasks - list all tasks, statuses, and signed URLs for previews
  fastify.get('/api/tasks', async (req, reply) => {
    try {
      const bucket = storage.bucket(bucketName);

      // 1. List all input files in parallel with result files
      const [inputFilesPromise, resultFilesPromise] = [
        bucket.getFiles({ prefix: `${bucketPrefix}/` }),
        bucket.getFiles({ prefix: 'results/' }),
      ];
      const [[inputFiles], [resultFiles]] = await Promise.all([inputFilesPromise, resultFilesPromise]);

      // 2. Download and parse all results in parallel to build a map of taskId -> result data
      const resultsMap = new Map<string, any>();
      await Promise.all(
        resultFiles.map(async (file) => {
          if (!file.name.endsWith('.json')) return;
          
          const parts = file.name.split('/');
          const taskIdJson = parts[parts.length - 1];
          const taskId = taskIdJson.substring(0, taskIdJson.length - '.json'.length);

          try {
            const [content] = await file.download();
            const data = JSON.parse(content.toString('utf-8'));
            resultsMap.set(taskId, data);
          } catch (e) {
            req.log.error(`Failed to download or parse result for task ${taskId}: ${e}`);
          }
        })
      );

      // 3. Process each input file and correlate with its result status
      const tasks = await Promise.all(
        inputFiles.map(async (file) => {
          const filename = file.name.substring(`${bucketPrefix}/`.length);
          if (!filename) return null; // skip the prefix placeholder itself

          const taskId = file.metadata.metadata?.taskId;
          if (!taskId) {
            req.log.warn(`File ${file.name} is missing a taskId in custom metadata`);
            return null;
          }

          const result = resultsMap.get(taskId);
          const status = result?.status || 'PENDING';

          // Generate short-lived read signed URL for the full image
          const [imageSignedUrl] = await file.getSignedUrl({
            version: 'v4',
            action: 'read',
            expires: Date.now() + 15 * 60 * 1000, // 15 minutes
          });

          // Generate short-lived read signed URL for thumbnail if it exists
          let thumbnailSignedUrl: string | undefined = undefined;
          if (result?.thumbnailPath) {
            const thumbFile = bucket.file(`thumbs/${taskId}.png`);
            try {
              const [url] = await thumbFile.getSignedUrl({
                version: 'v4',
                action: 'read',
                expires: Date.now() + 15 * 60 * 1000,
              });
              thumbnailSignedUrl = url;
            } catch (e) {
              req.log.error(`Failed to generate signed URL for thumbnail thumbs/${taskId}.png: ${e}`);
            }
          }

          return {
            taskId: taskId,
            filename: filename,
            gcsPath: `gs://${bucketName}/${file.name}`,
            uploadedAt: file.metadata.timeCreated,
            status: status,
            imageSignedUrl: imageSignedUrl,
            thumbnailSignedUrl: thumbnailSignedUrl,
            resultDetails: result || null,
          };
        })
      );

      // Filter out nulls (folders or files missing task IDs)
      const activeTasks = tasks.filter((t) => t !== null);

      reply.send(activeTasks);
    } catch (error) {
      req.log.error(`Failed to list tasks: ${error}`);
      reply.status(500).send({ error: 'Failed to list tasks' });
    }
  });

  // DELETE /api/tasks/:taskId - delete input, results, and thumbnails
  fastify.delete<{
    Params: { taskId: string };
  }>('/api/tasks/:taskId', async (req, reply) => {
    const { taskId } = req.params;
    try {
      const bucket = storage.bucket(bucketName);
      req.log.info(`Request to delete task: ${taskId}`);

      // 1. Try to find the input filename. We first check the result file if it exists
      let inputPath: string | null = null;
      const resultFile = bucket.file(`results/${taskId}.json`);
      let resultExists = false;

      try {
        const [exists] = await resultFile.exists();
        resultExists = exists;
        if (exists) {
          const [content] = await resultFile.download();
          const data = JSON.parse(content.toString('utf-8'));
          if (data.gcsPath) {
            // parse gs://bucket/prefix/filename
            const gcsPath = data.gcsPath;
            if (gcsPath.startsWith('gs://')) {
              const pathWithoutGs = gcsPath.substring(5);
              const parts = pathWithoutGs.split('/');
              if (parts.length > 1) {
                // reconstitute the object path: prefix/filename
                inputPath = parts.slice(1).join('/');
              }
            }
          }
        }
      } catch (e) {
        req.log.warn(`Could not extract input path from results file: ${e}`);
      }

      // 2. Fallback: Scan the input directory for a file containing this taskId in metadata
      if (!inputPath) {
        req.log.info(`Scanning input/ directory for taskId: ${taskId}`);
        const [files] = await bucket.getFiles({ prefix: `${bucketPrefix}/` });
        for (const file of files) {
          if (file.metadata.metadata?.taskId === taskId) {
            inputPath = file.name;
            break;
          }
        }
      }

      // 3. Perform deletions
      const deletions: Promise<any>[] = [];

      if (inputPath) {
        req.log.info(`Queueing deletion of input image: ${inputPath}`);
        deletions.push(bucket.file(inputPath).delete().catch((e) => req.log.error(`Failed to delete ${inputPath}: ${e}`)));
      } else {
        req.log.warn(`Could not find input image for taskId: ${taskId}`);
      }

      if (resultExists) {
        req.log.info(`Queueing deletion of task result: results/${taskId}.json`);
        deletions.push(resultFile.delete().catch((e) => req.log.error(`Failed to delete results/${taskId}.json: ${e}`)));
      }

      const thumbFile = bucket.file(`thumbs/${taskId}.png`);
      try {
        const [thumbExists] = await thumbFile.exists();
        if (thumbExists) {
          req.log.info(`Queueing deletion of thumbnail: thumbs/${taskId}.png`);
          deletions.push(thumbFile.delete().catch((e) => req.log.error(`Failed to delete thumbnail: ${e}`)));
        }
      } catch (e) {
        req.log.error(`Failed to check thumbnail existence: ${e}`);
      }

      await Promise.all(deletions);

      reply.status(200).send({ message: `Task ${taskId} deleted successfully.` });
    } catch (error) {
      req.log.error(`Failed to delete task ${taskId}: ${error}`);
      reply.status(500).send({ error: 'Failed to delete task' });
    }
  });
}
