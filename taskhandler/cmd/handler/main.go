package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	"image/png"
	"io/ioutil"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"cloud.google.com/go/storage"
	"go.uber.org/zap"
)

const (
	DefaultInitSleepSec        int = 30
	DefaultHandleInputSleepSec int = 2
)

type ServiceConfig struct {
	InitSleepSec        int
	HandleInputSleepSec int
	GcsClient           storage.Client
}

type TaskHandler struct {
	cfg *ServiceConfig
	log *zap.Logger
}

type TaskStruct struct {
	B64Input   *string `json:"b64input"`   // b64 encoded payload (skip the storage integration)
	Path       string  `json:"gcsPath"`    // file location of the uploaded file
	JobId      string  `json:"jobId"`      // UUID of the overall job
	SignedUrl  string  `json:"signedUrl"`  // this is kind of useless info
	SessionUrl string  `json:"sessionUrl"` // use this for resumable uploads
}

func InitServiceConfig(ctx context.Context) (*ServiceConfig, error) {
	cfg := &ServiceConfig{}

	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, err
	}

	cfg.GcsClient = *client

	initSleepSec, err := strconv.Atoi(os.Getenv("INIT_SLEEP_SEC"))
	if err != nil {
		cfg.InitSleepSec = DefaultInitSleepSec
	} else {
		cfg.InitSleepSec = initSleepSec
	}

	handleInputSleepSec, err := strconv.Atoi(os.Getenv("HANDLE_INPUT_SLEEP_SEC"))
	if err != nil {
		cfg.HandleInputSleepSec = DefaultHandleInputSleepSec
	} else {
		cfg.HandleInputSleepSec = handleInputSleepSec
	}

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

func (h *TaskHandler) handleInput(i image.Image) {
	// maybe sleep here to simulate long running task
	time.Sleep(time.Duration(h.cfg.HandleInputSleepSec) * time.Second)
}

func (h *TaskHandler) handleB64(w http.ResponseWriter, t TaskStruct) {
	h.log.Sugar().Debugf("handling b64 encoded input ...")

	// decodedBytes, err := base64.StdEncoding.DecodeString(*t.B64Input)
	// if err != nil {
	// 	h.log.Sugar().Errorf("error decoding string: %s", err)
	// 	w.WriteHeader(http.StatusBadRequest)
	// 	return
	// }

	reader := base64.NewDecoder(base64.StdEncoding, strings.NewReader(*t.B64Input))

	// reader := bytes.NewReader(decodedBytes)

	img, err := png.Decode(reader)
	if err != nil {
		h.log.Sugar().Errorf("error decoding image: %s", err)
		w.WriteHeader(http.StatusBadRequest)
		return
	}

	h.log.Sugar().Infof("Decoded image format %s, %dx%d ...", "png", img.Bounds().Dx(), img.Bounds().Dy())

	h.handleInput(img)

	w.WriteHeader(http.StatusOK)
}

// healthCheckHandler responds to health check requests.
// It should return a 200 OK status if the server is healthy.
func (h *TaskHandler) HealthCheckHandler(w http.ResponseWriter, r *http.Request) {
	// In a simple case, just returning a 200 OK is sufficient
	// if the only check is whether the HTTP server is listening.
	w.WriteHeader(http.StatusOK) // HTTP 200 OK
	fmt.Fprintf(w, "OK")         // Optional: return a body
	h.log.Sugar().Debug("Health check request received: OK")
}

func (h *TaskHandler) Handler(w http.ResponseWriter, req *http.Request) {
	switch req.Method {
	case "POST":
		body, err := ioutil.ReadAll(req.Body)
		if err != nil {
			h.log.Sugar().Errorf("error reading body: %s", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		var t TaskStruct
		err = json.Unmarshal(body, &t)
		if err != nil {
			h.log.Sugar().Errorf("error decoding body: %s", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		h.log.Sugar().Infof("handling request: %s %s, %+v\n", req.Method, req.URL.Path, t)
		if t.B64Input != nil {

			// if the request is inline, handle it
			h.handleB64(w, t)
			return
		}

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

		// TODO download and handle the file
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
	http.HandleFunc("/health", handler.HealthCheckHandler)

	logger.Sugar().Infof("Simulating initialization of %d seconds ...", cfg.InitSleepSec)
	time.Sleep(time.Duration(cfg.InitSleepSec) * time.Second)
	logger.Sugar().Info("Listning on port 8090\n")
	http.ListenAndServe(":8090", nil)
}
