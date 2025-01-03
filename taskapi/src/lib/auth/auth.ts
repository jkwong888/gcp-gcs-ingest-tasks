
// import { fastifyPlugin } from 'fastify-plugin';
// import { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { OAuth2Client } from 'google-auth-library';
import { conf } from '../conf/config';
import logger from '../log/log';

  const authClient = new OAuth2Client();

  export async function validateIDToken(token: string/*request: FastifyRequest, reply: FastifyReply*/): Promise<void> {
      // Verify that the push request originates from Cloud Pub/Sub.
      /*try {
        request.log.info(`validate auth header: ${request.headers.authorization}`);
        // Get the Cloud Pub/Sub-generated JWT in the "Authorization" header.
        const authHeader = request.headers.authorization || "";
      */
        //const [, token] = authHeader.match(/Bearer (.*)/) || [];
        if (!token) {
          //reply.status(401).send();
          // TODO: typesafe error
          logger.error("null token passed");
          throw new Error("Unauthorized");
        }
    
        // Verify and decode the JWT.
        // Note: For high volume push requests, it would save some network
        // overhead if you verify the tokens offline by decoding them using
        // Google's Public Cert; caching already seen tokens works best when
        // a large volume of messages have prompted a single push server to
        // handle them, in which case they would all share the same token for
        // a limited time window.
        const ticket = await authClient.verifyIdToken({
          idToken: token,
        }).catch ((error) => {
          logger.error(`ID token verify failed: ${error}`)
          throw new Error("Unauthorized");
          //reply.status(401).send();
          //return;
        });
    
        const claim = ticket?.getPayload();
        if (claim == undefined) {
          logger.error(`No claims in token`);
          //reply.status(401).send();
          //return;
          throw new Error(`No claims in token`);
        }
    
        // IMPORTANT: you should validate claim details not covered
        // by signature and audience verification above, including:
        //   - Ensure that `claim.email` is equal to the expected service
        //     account set up in the push subscription settings.
        //   - Ensure that `claim.email_verified` is set to true.
    
        if (!claim.email_verified) {
          logger.error(`email_verified = false`);
          // reply.status(401).send();
          // return;
          throw new Error(`email_verified = false`);
        }

        // TODO - how to pass this in
        const storageServiceAccountEmail = conf.storageServiceAccountEmail;
    
        if (claim.email != conf.storageServiceAccountEmail) {
          logger.error(`email in token ${claim.email} does not match expected email: ${storageServiceAccountEmail}`);
          // reply.status(401).send();
          // return;
          throw new Error(`Unauthorized`);
        }
      // } catch (e) {
      //   reply.status(401).send(e);
      // }
    }