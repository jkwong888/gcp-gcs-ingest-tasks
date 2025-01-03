import fastify, { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';

async function ping (fastify: FastifyInstance, _options: Object) {

    fastify.get(
        '/ping', 
        async (request: FastifyRequest, reply: FastifyReply) => {
            return 'pong\n'
        }
    );
}
