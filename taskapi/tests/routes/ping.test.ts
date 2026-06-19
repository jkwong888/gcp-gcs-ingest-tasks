import { buildApp } from '../../src/index';

describe('GET /ping', () => {
  it('should respond with pong', async () => {
    const app = buildApp();
    const response = await app.inject({
      method: 'GET',
      url: '/ping',
    });

    expect(response.statusCode).toBe(200);
    expect(response.body).toBe('pong\n');
  });
});
