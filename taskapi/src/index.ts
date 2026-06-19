import fastify, { FastifyInstance } from 'fastify';
import { fastifyMultipart } from '@fastify/multipart';
import fastifyStatic from '@fastify/static';
import path from 'path';
import { logger } from './config';
import { pingRoutes } from './routes/ping';
import { uploadRoutes } from './routes/upload';
import { notificationRoutes } from './routes/notification';
import { taskRoutes } from './routes/tasks';

export function buildApp(): FastifyInstance {
  const app = fastify({
    logger: logger,
  });

  // Register fastify multipart upload plugin
  app.register(fastifyMultipart);

  // Register static file plugin to serve public/ folder at /
  app.register(fastifyStatic, {
    root: path.join(__dirname, '../public'),
    prefix: '/',
  });

  // Register routes
  app.register(pingRoutes);
  app.register(uploadRoutes);
  app.register(notificationRoutes);
  app.register(taskRoutes);

  return app;
}

if (require.main === module) {
  const app = buildApp();
  const port = process.env.PORT ? parseInt(process.env.PORT) : 8000;
  const host = '0.0.0.0';

  app.listen({ host, port }, (err, address) => {
    if (err) {
      logger.error(err);
      process.exit(1);
    }
    logger.info(`Server listening at ${address}`);
  });
}