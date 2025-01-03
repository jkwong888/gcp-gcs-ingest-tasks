import fastify from 'fastify';
import { Config } from '@/src/lib/types/config';

declare module 'fastify' {
  export interface FastifyInstance<
    HttpServer = Server,
    HttpRequest = IncomingMessage,
    HttpResponse = ServerResponse,
  > {
    conf: Config;
  }
}