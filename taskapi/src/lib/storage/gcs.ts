
async function generateV4UploadSignedUrl(fileName: string, action: 'write' | 'resumable', contentType: string | undefined) {
    // These options will allow temporary uploading of the file with outgoing
    // Content-Type: application/octet-stream header.
    const options = {
      version: 'v4' as const,
      action: action,
      expires: Date.now() + 15 * 60 * 1000, // 15 minutes
      contentType: contentType || undefined,
    };
  
    // Get a v4 signed URL for uploading file
    const [url] = await storage
      .bucket(bucketName)
      .file(`${bucketPrefix}/${fileName}`)
      .getSignedUrl(options)
      .catch((error) => {
        throw error;
      });
  
    logger.info(`Generated PUT ${action} signed URL: ${url}`);
    return url;
  }