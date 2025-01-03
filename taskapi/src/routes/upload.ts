
  

  /* accept a single multi-part file upload, stream it into storage and create a cloud task to handle it
   needs multiple instance of this API to handle multiple files, but task will be created synchronously when file upload completes
   use curl -F '<filename>=@/path/to/file' <url> to upload a file
*/
fastify.post(
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
fastify.post<{ 
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


fastify.post<{ 
Body: FromSchema<typeof UploadBody> 
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