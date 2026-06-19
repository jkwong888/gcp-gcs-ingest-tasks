import { FastifyReply, FastifyRequest } from 'fastify';
import { authClient, storageServiceAccountEmail } from '../config';

export async function validateIDToken(request: FastifyRequest, reply: FastifyReply): Promise<void> {
  // Verify that the push request originates from Cloud Pub/Sub.
  try {
    request.log.info(`validate auth header: ${request.headers.authorization}`);
    // Get the Cloud Pub/Sub-generated JWT in the "Authorization" header.
    const authHeader = request.headers.authorization || "";
    const [, token] = authHeader.match(/Bearer (.*)/) || [];
    if (!token) {
      reply.status(401).send();
      return;
    }

    // Verify and decode the JWT.
    const ticket = await authClient.verifyIdToken({
      idToken: token,
    }).catch ((error) => {
      request.log.error(`ID token verify failed: ${error}`);
      reply.status(401).send();
      return;
    });

    const claim = ticket?.getPayload();
    if (claim == undefined) {
      request.log.error(`No claims in token`);
      reply.status(401).send();
      return;
    }

    if (!claim.email_verified) {
      request.log.error(`email_verified = false`);
      reply.status(401).send();
      return;
    }

    if (claim.email != storageServiceAccountEmail) {
      request.log.error(`email in token ${claim.email} does not match expected email: ${storageServiceAccountEmail}`);
      reply.status(401).send();
      return;
    }
  } catch (e) {
    reply.status(401).send(e);
  }
}
