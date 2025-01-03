
export interface Config {
    bucketName: string;
    bucketPrefix: string;
    queueName: string;
    projectId: string;
    region: string;
    taskHandlerUrl: string;
    taskServiceAccountEmail: string;
    storageServiceAccountEmail: string;
}