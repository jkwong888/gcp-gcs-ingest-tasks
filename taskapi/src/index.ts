import Fastify, { FastifyReply, FastifyRequest } from 'fastify'
import util from 'util';
import { v4 as uuidv4 } from 'uuid';
import { FromSchema } from 'json-schema-to-ts';
import { Storage } from '@google-cloud/storage';
import { pipeline } from 'stream';
import { fastifyMultipart } from '@fastify/multipart';

import mime from 'mime-types';

import conf from './lib/conf/config';
import logger from './lib/log/log';

const storage = new Storage();

const pump = util.promisify(pipeline);

const fastify = Fastify({
  logger: logger,
});

// use fastify multipart upload plugin
fastify.register(fastifyMultipart);

fastify.decorate('conf', conf);

// fastify.decorate('validateIdToken', )

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








fastify.listen({ 
  host: '0.0.0.0', 
  port: 8000 }, 
  (err, address) => {
  if (err) {
    logger.error(err)
    process.exit(1)
  }
  logger.info(`Server listening at ${address}`)
})