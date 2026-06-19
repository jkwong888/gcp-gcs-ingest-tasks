import { buildApp } from '../../src/index';

describe('Upload Routes', () => {
  let app: ReturnType<typeof buildApp>;

  beforeAll(() => {
    app = buildApp();
  });

  describe('POST /upload', () => {
    it('should upload a multipart image file and stream to GCS', async () => {
      const boundary = '----TestBoundary12345';
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="file"; filename="test-image.png"',
        'Content-Type: image/png',
        '',
        'fake-png-data-here',
        `--${boundary}--`,
        ''
      ].join('\r\n');

      const response = await app.inject({
        method: 'POST',
        url: '/upload',
        headers: {
          'content-type': `multipart/form-data; boundary=${boundary}`,
        },
        payload: Buffer.from(body),
      });

      expect(response.statusCode).toBe(201);
      const resJson = JSON.parse(response.body);
      expect(resJson.gcsPath).toBe('gs://test-bucket/upload/test-image.png');
      expect(resJson.taskId).toBeDefined();
      expect(typeof resJson.taskId).toBe('string');
    });

    it('should return 400 if file is not an image', async () => {
      const boundary = '----TestBoundary12345';
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="file"; filename="test-file.txt"',
        'Content-Type: text/plain',
        '',
        'hello text file',
        `--${boundary}--`,
        ''
      ].join('\r\n');

      const response = await app.inject({
        method: 'POST',
        url: '/upload',
        headers: {
          'content-type': `multipart/form-data; boundary=${boundary}`,
        },
        payload: Buffer.from(body),
      });

      expect(response.statusCode).toBe(400);
      const resJson = JSON.parse(response.body);
      expect(resJson.error).toContain('MIME type image/*');
    });

    it('should return 400 if no file is provided', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/upload',
        headers: {
          'content-type': 'multipart/form-data; boundary=----EmptyBoundary',
        },
        payload: Buffer.from(''),
      });

      expect(response.statusCode).toBe(400);
    });
  });

  describe('POST /uploadSignedUrl', () => {
    it('should return 201 with signed URL, gcsPath, and taskId', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadSignedUrl',
        payload: {
          filename: 'image.png',
          contentType: 'image/png',
        },
      });

      expect(response.statusCode).toBe(201);
      expect(response.headers['location']).toBe('http://mock-signed-url');
      
      const resJson = JSON.parse(response.body);
      expect(resJson.gcsPath).toBe('gs://test-bucket/upload/image.png');
      expect(resJson.signedUrl).toBe('http://mock-signed-url');
      expect(resJson.expectedContentType).toBe('image/png');
      expect(resJson.taskId).toBeDefined();
    });

    it('should auto-detect content type if not provided and allow if it is an image', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadSignedUrl',
        payload: {
          filename: 'picture.jpg',
        },
      });

      expect(response.statusCode).toBe(201);
      const resJson = JSON.parse(response.body);
      expect(resJson.expectedContentType).toBe('image/jpeg');
      expect(resJson.taskId).toBeDefined();
    });

    it('should return 400 if auto-detected type is not an image', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadSignedUrl',
        payload: {
          filename: 'document.pdf',
        },
      });

      expect(response.statusCode).toBe(400);
    });

    it('should return 400 if filename is missing', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadSignedUrl',
        payload: {},
      });

      expect(response.statusCode).toBe(400);
    });
  });

  describe('POST /uploadResumable', () => {
    it('should return 201 with sessionUrl, gcsPath, and taskId', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadResumable',
        payload: {
          filename: 'graphic.gif',
        },
      });

      expect(response.statusCode).toBe(201);
      expect(response.headers['location']).toBe('http://mock-signed-url');

      const resJson = JSON.parse(response.body);
      expect(resJson.gcsPath).toBe('gs://test-bucket/upload/graphic.gif');
      expect(resJson.sessionUrl).toBe('http://mock-signed-url');
      expect(resJson.taskId).toBeDefined();
    });

    it('should return 400 if filename is missing', async () => {
      const response = await app.inject({
        method: 'POST',
        url: '/uploadResumable',
        payload: {},
      });

      expect(response.statusCode).toBe(400);
    });
  });
});
