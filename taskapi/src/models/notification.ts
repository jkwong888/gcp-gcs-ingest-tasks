export const pubsubUploadNotification = {
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
