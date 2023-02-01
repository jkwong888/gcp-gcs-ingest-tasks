# Cloud Run based ingest process


1. build the taskapi and taskhandler images and push to GCR or AR.
2. take the image repo URIs and put it in terraform variables: 
3. run the terraform
4. to test, run the code in taskgen to upload a random image to GCS and watch the pipeline trigger a cloud task to be handled by the task handler.