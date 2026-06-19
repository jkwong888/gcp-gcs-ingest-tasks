// Set default environment variables for tests
process.env.BUCKET_NAME = 'test-bucket';
process.env.BUCKET_PREFIX = 'upload';
process.env.STORAGE_SERVICE_ACCOUNT_EMAIL = 'mock-storage-sa@project.iam.gserviceaccount.com';
process.env.PROJECT_ID = 'test-project';
process.env.REGION = 'us-central1';
process.env.QUEUE_NAME = 'test-queue';
process.env.TASK_HANDLER_URL = 'http://mock-task-handler';
process.env.TASKS_SERVICE_ACCOUNT_EMAIL = 'mock-tasks-sa@project.iam.gserviceaccount.com';

// Global mocks for GCP services
import { Writable } from 'stream';

// Mock Storage
jest.mock('@google-cloud/storage', () => {
  const mockFile = {
    name: 'upload/test-image.png',
    metadata: {
      timeCreated: '2026-06-19T16:00:00Z',
      metadata: {
        taskId: 'mock-task-id',
      },
    },
    getSignedUrl: jest.fn().mockResolvedValue(['http://mock-signed-url']),
    createWriteStream: jest.fn().mockImplementation(() => {
      return new Writable({
        write(chunk, encoding, callback) {
          callback();
        }
      });
    }),
    save: jest.fn().mockResolvedValue(undefined),
    download: jest.fn().mockResolvedValue([
      Buffer.from(
        JSON.stringify({
          jobId: 'mock-task-id',
          status: 'COMPLETED',
          updatedAt: '2026-06-19T16:01:00Z',
          width: 100,
          height: 100,
          format: 'png',
          thumbnailPath: 'gs://test-bucket/thumbs/mock-task-id.png',
        })
      ),
    ]),
    exists: jest.fn().mockResolvedValue([true]),
    delete: jest.fn().mockResolvedValue(undefined),
  };

  const mockBucket = {
    file: jest.fn().mockReturnValue(mockFile),
    getFiles: jest.fn().mockImplementation((options) => {
      if (options?.prefix && options.prefix.includes('upload')) {
        return Promise.resolve([[mockFile]]);
      }
      if (options?.prefix && options.prefix.includes('results')) {
        const resultFile = {
          ...mockFile,
          name: 'results/mock-task-id.json',
        };
        return Promise.resolve([[resultFile]]);
      }
      return Promise.resolve([[]]);
    }),
  };

  return {
    Storage: jest.fn().mockImplementation(() => ({
      bucket: jest.fn().mockReturnValue(mockBucket),
    })),
  };
});

// Mock Cloud Tasks
jest.mock('@google-cloud/tasks', () => {
  return {
    CloudTasksClient: jest.fn().mockImplementation(() => ({
      queuePath: jest.fn().mockReturnValue('projects/mock-project/locations/mock-region/queues/mock-queue'),
      createTask: jest.fn().mockResolvedValue([{ name: 'projects/mock-project/locations/mock-region/queues/mock-queue/tasks/mock-task-id' }]),
    })),
  };
});

// Mock Google Auth Library
jest.mock('google-auth-library', () => {
  return {
    OAuth2Client: jest.fn().mockImplementation(() => ({
      verifyIdToken: jest.fn().mockResolvedValue({
        getPayload: () => ({
          email_verified: true,
          email: 'mock-storage-sa@project.iam.gserviceaccount.com',
        }),
      }),
    })),
  };
});

// Mock Jimp image processing library
jest.mock('jimp', () => {
  const mockJimpInstance = {
    bitmap: { width: 100, height: 100 },
    resize: jest.fn().mockReturnThis(),
    getBuffer: jest.fn().mockResolvedValue(Buffer.from('fake-png-thumbnail-bytes')),
  };
  return {
    __esModule: true,
    Jimp: {
      read: jest.fn().mockResolvedValue(mockJimpInstance),
    },
    JimpMime: {
      png: 'image/png',
      jpeg: 'image/jpeg',
      gif: 'image/gif',
      bmp: 'image/bmp',
      tiff: 'image/tiff',
    }
  };
});

beforeEach(() => {
  jest.clearAllMocks();
});
