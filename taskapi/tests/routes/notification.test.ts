import { buildApp } from '../../src/index';
import { authClient, taskClient } from '../../src/config';

describe('POST /uploadNotification', () => {
  let app: ReturnType<typeof buildApp>;

  beforeAll(() => {
    app = buildApp();
  });

  const validPayload = {
    message: {
      attributes: {
        bucketId: 'test-bucket',
        eventType: 'OBJECT_FINALIZE',
        objectId: 'upload/video.mp4',
        eventTime: '2026-06-19T16:00:00Z',
        payloadFormat: 'JSON_API_V1',
      },
      data: 'eyJmb28iOiJiYXIifQ==', // base64 encoded JSON (e.g. {"foo":"bar"})
      messageId: '12345',
      publishTime: '2026-06-19T16:00:01Z',
    },
    subscription: 'projects/test-project/subscriptions/test-sub',
  };

  it('should successfully process notification and trigger cloud task (local dev bypass mode)', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      // No auth headers
      payload: validPayload,
    });

    expect(response.statusCode).toBe(201);
    const resJson = JSON.parse(response.body);
    expect(resJson.jobId).toBeDefined();
    expect(resJson.taskId).toBe('projects/mock-project/locations/mock-region/queues/mock-queue/tasks/mock-task-id');
    expect(resJson.gcsPath).toBe('gs://test-bucket/upload/video.mp4');
  });

  it('should successfully process notification and trigger cloud task (IAP mode)', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      headers: {
        'x-goog-authenticated-user-email': 'accounts.google.com:mock-storage-sa@project.iam.gserviceaccount.com',
      },
      payload: validPayload,
    });

    expect(response.statusCode).toBe(201);
    const resJson = JSON.parse(response.body);
    expect(resJson.jobId).toBeDefined();
    expect(resJson.taskId).toBe('projects/mock-project/locations/mock-region/queues/mock-queue/tasks/mock-task-id');
  });

  it('should return 403 if IAP email does not match expected storage SA', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      headers: {
        'x-goog-authenticated-user-email': 'accounts.google.com:wrong-user@gmail.com',
      },
      payload: validPayload,
    });

    expect(response.statusCode).toBe(403);
  });

  it('should return 200 and ignore the event if eventType is not OBJECT_FINALIZE', async () => {
    const payload = {
      ...validPayload,
      message: {
        ...validPayload.message,
        attributes: {
          ...validPayload.message.attributes,
          eventType: 'OBJECT_METADATA_UPDATE',
        },
      },
    };

    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      payload: payload,
    });

    expect(response.statusCode).toBe(200);
  });

  it('should return 200 and ignore if bucketId does not match BUCKET_NAME', async () => {
    const payload = {
      ...validPayload,
      message: {
        ...validPayload.message,
        attributes: {
          ...validPayload.message.attributes,
          bucketId: 'wrong-bucket',
        },
      },
    };

    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      payload: payload,
    });

    expect(response.statusCode).toBe(200);
  });

  it('should return 200 and ignore if objectId does not start with BUCKET_PREFIX', async () => {
    const payload = {
      ...validPayload,
      message: {
        ...validPayload.message,
        attributes: {
          ...validPayload.message.attributes,
          objectId: 'different-folder/video.mp4',
        },
      },
    };

    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      payload: payload,
    });

    expect(response.statusCode).toBe(200);
  });

  it('should return 500 if cloud tasks creation fails', async () => {
    (taskClient.createTask as jest.Mock).mockRejectedValueOnce(new Error('Cloud Tasks service unavailable'));

    const response = await app.inject({
      method: 'POST',
      url: '/uploadNotification',
      payload: validPayload,
    });

    expect(response.statusCode).toBe(500);
  });
});
