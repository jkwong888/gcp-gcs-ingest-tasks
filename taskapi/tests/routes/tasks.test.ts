import { buildApp } from '../../src/index';
import { storage } from '../../src/config';

describe('Task Routes', () => {
  let app: ReturnType<typeof buildApp>;

  beforeAll(() => {
    app = buildApp();
  });

  describe('GET /api/tasks', () => {
    it('should successfully list tasks consolidated with GCS results and signed URLs', async () => {
      const response = await app.inject({
        method: 'GET',
        url: '/api/tasks',
      });

      expect(response.statusCode).toBe(200);
      const resJson = JSON.parse(response.body);
      
      expect(Array.isArray(resJson)).toBe(true);
      expect(resJson.length).toBe(1);

      const task = resJson[0];
      expect(task.taskId).toBe('mock-task-id');
      expect(task.filename).toBe('test-image.png');
      expect(task.status).toBe('COMPLETED');
      expect(task.imageSignedUrl).toBe('http://mock-signed-url');
      expect(task.thumbnailSignedUrl).toBe('http://mock-signed-url');
      expect(task.resultDetails).toEqual({
        jobId: 'mock-task-id',
        status: 'COMPLETED',
        updatedAt: '2026-06-19T16:01:00Z',
        width: 100,
        height: 100,
        format: 'png',
        thumbnailPath: 'gs://test-bucket/thumbs/mock-task-id.png',
      });
    });
  });

  describe('DELETE /api/tasks/:taskId', () => {
    it('should successfully delete input, results, and thumbnail files', async () => {
      const response = await app.inject({
        method: 'DELETE',
        url: '/api/tasks/mock-task-id',
      });

      expect(response.statusCode).toBe(200);
      const resJson = JSON.parse(response.body);
      expect(resJson.message).toContain('deleted successfully');
    });
  });
});
