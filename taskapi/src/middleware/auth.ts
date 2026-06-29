import { FastifyReply, FastifyRequest } from 'fastify';
import { storageServiceAccountEmail } from '../config';

/**
 * Validates that the incoming request originates from the authorized GCS storage notification system.
 * 
 * In production (behind IAP), it verifies the cryptographically secure header `X-Goog-Authenticated-User-Email`
 * injected by IAP, ensuring the caller matches our configured storage service account.
 * 
 * In local development (no IAP), it bypasses validation to allow easy testing.
 */
export async function validateNotificationCaller(request: FastifyRequest, reply: FastifyReply): Promise<void> {
  const iapUserEmailHeader = request.headers['x-goog-authenticated-user-email'] as string;
  
  if (iapUserEmailHeader) {
    request.log.info(`Validating notification caller via IAP header: ${iapUserEmailHeader}`);
    
    // IAP prefixes the email (e.g., "accounts.google.com:storage@project.iam.gserviceaccount.com")
    const email = iapUserEmailHeader.split(':').pop() || "";
    
    if (email !== storageServiceAccountEmail) {
      request.log.error(`IAP authenticated email [${email}] does not match expected storage SA: [${storageServiceAccountEmail}]`);
      reply.status(403).send({ error: 'Forbidden: Unauthorized service account' });
      return;
    }
    
    request.log.info(`Caller successfully authorized: ${email}`);
    return;
  }

  // Fallback for local development / testing without IAP
  request.log.warn('No IAP identity header found. Bypassing caller validation (local development mode).');
}
