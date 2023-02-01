# task API

## environment variables:

```
BUCKET_NAME       # name of bucket to upload files to
BUCKET_PREFIX     # prefix of files in the bucket
QUEUE_NAME        # name of cloud tasks queue
PROJECT_ID        # project id where the cloud tasks queue is located
REGION            # region where the cloud tasks queue is located
TASK_HANDLER_URL  # url of the task handler to call after files are uploaded
TASKS_SERVICE_ACCOUNT_EMAIL   # service account email representing the tasks (will be used to trigger the task handler url)
STORAGE_SERVICE_ACCOUNT_EMAIL # service account email representing the storage notification (notifications will have a token containing this identity)
```

## deploy steps


1. Build image and deploy to Cloud Run
2. Create a pubsub subscription on the storage notification topic and set it to `https://<cloud run url>/uploadNotification`.  Make sure the subscription uses the account in `${STORAGE_SERVICE_ACCOUNT_EMAIL}`.
3. Upload a file:

   - `POST /upload` to upload a file synchronously (using multipart upload):

     ```
     curl -F '<upload_file>=@/path/to/file' <cloud run URL>/upload
     ```

   - `POST /uploadSignedUrl` to get a signed URL to upload a single file to:

     ```
     curl -i -X POST -H "Content-Type: application/json"  -d '{"filename":"<filename>"}' <cloud run URL>/uploadSignedUrl
     ```

     will return a URL in the location header (as well as a JSON response containing the URL), then:
     ```
     curl -X PUT --upload-file /path/to/file -H "Content-Type: <mime-type>" '<signed URL>'
     ```

     the api will attempt to guess the mime type, but you can also set it yourself in the request json.

    - `POST /uploadResumable` to get a resumable session URL to upload a file:
      
      ```
      curl -i -X POST -H "Content-Type: application/json"  -d '{"filename":"<filename>"}' <cloud run URL>/uploadSignedUrl
      ```

      will return a session URL in the body.  start the upload session:

      ```
      curl -i -X POST -H "x-goog-resumable: start" <sessionUrl>
      ```

      will return a signed URL in the `Location` header, which you can use to PUT your file:

      ```
      curl -i -X PUT --upload-file /path/to/file -H "Content-Type: <mime-type>" '<signedURL>'
      ```

      note that if the file is very large, you can use break up the content into chunks in the PUT request using the `Content-Range` header with the byte offsets being uploaded in the put body.



      

3. Once the file is in GCS, a pubsub notification subscription should call the task api on the following URL, `POST /uploadNotification`.  This triggers a cloud task (to be handled by the taskhandler)
  - note the token passed to this must be signed by google and contain the email address of the service account expected in the `${STORAGE_SERVICE_ACCOUNT_EMAIL}` environment variable.