package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"io/ioutil"
	"net/http"

	"cloud.google.com/go/storage"
	"go.uber.org/zap"
)

type ServiceConfig struct {
	GcsClient storage.Client
}

type TaskHandler struct {
	cfg 	*ServiceConfig
	log		*zap.Logger
}

type TaskStruct struct {
	Path string `json:"gcsPath"`			// file location of the uploaded file
	JobId string `json:"jobId"`				// UUID of the overall job
	SignedUrl string `json:"signedUrl"` 	// this is kind of useless info
	SessionUrl string `json:"sessionUrl"`	// use this for resumable uploads
}

func InitServiceConfig(ctx context.Context) (*ServiceConfig, error) {
	cfg := &ServiceConfig{}

	client, err := storage.NewClient(ctx);
	if err != nil {
		return nil, err
	}

	cfg.GcsClient = *client

	return cfg, nil
}

func InitTaskHandler(cfg *ServiceConfig, logger *zap.Logger) *TaskHandler {
	return &TaskHandler{
		cfg: cfg,
		log: logger,
	}
}

func (h *TaskHandler) parseBucketPath(gcsPath string) (string, string, error) {
	if !strings.HasPrefix(gcsPath, "gs://") {
		return "", "", fmt.Errorf("invalid GCS location: %v", gcsPath)
	}

	path := strings.TrimPrefix(gcsPath, "gs://")
	bucketArr := strings.SplitN(path, "/", 2)
	bucketName := bucketArr[0]
	filePath := bucketArr[1]

	return bucketName, filePath, nil
}

func (h *TaskHandler) Handler(w http.ResponseWriter, req *http.Request) {
	switch req.Method {
		case "POST":
			body, err := ioutil.ReadAll(req.Body)
			if err != nil {
				panic(err)
			}

			var t TaskStruct
			json.Unmarshal(body, &t)
			h.log.Sugar().Infof("handling request: %s %s, %+v\n", req.Method, req.URL.Path, t)

			// TODO: if sessionUrl is not null, check if the session is still open

			// check if the file exists yet
			bucketName, objPath, err := h.parseBucketPath(t.Path)
			if err != nil {
				h.log.Sugar().Infof("Error parsing path %v: %v\n", t.Path, err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}

			// does the bucket exist?  400 if not
			bucket := h.cfg.GcsClient.Bucket(bucketName)
			if bucket == nil {
				h.log.Sugar().Errorf("Bucket not found: %v\n", bucketName)
				w.WriteHeader(http.StatusBadRequest)
				return
			}

			// does the object exist in the bucket?  404 if not
			file := bucket.Object(objPath)
			_, err = file.Attrs(context.TODO())
			if err != nil {
				if err == storage.ErrObjectNotExist {
					h.log.Sugar().Errorf("Object not found in bucket %v: %v\n", bucketName, objPath)
					w.WriteHeader(http.StatusNotFound)
					return
				}

				// some other error, retry later
				h.log.Sugar().Errorf("error: %v", err)
				w.WriteHeader(http.StatusInternalServerError)
			}

			// if the file exists, status is OK
			h.log.Sugar().Infof("found bucket %v, path %v\n", bucketName, objPath)
			w.WriteHeader(http.StatusOK)

		default:
			w.WriteHeader(http.StatusNotFound)
	}
}

func main() {
	ctx := context.Background()

	logger, err := zap.NewProduction()
	if err != nil {
		panic(err)
	}

	defer logger.Sync()
	cfg, err := InitServiceConfig(ctx)
	if err != nil {
		panic(err)
	}


	handler := InitTaskHandler(cfg, logger)

    http.HandleFunc("/", handler.Handler)
	logger.Sugar().Info("Listning on port 8090\n")
    http.ListenAndServe(":8090", nil)
}