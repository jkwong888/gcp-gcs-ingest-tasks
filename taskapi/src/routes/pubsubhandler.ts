
fastify.post<{ 
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