package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
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
	if len(bucketArr) < 2 {
		return "", "", fmt.Errorf("invalid GCS location format: %v", gcsPath)
	}
	bucketName := bucketArr[0]
	filePath := bucketArr[1]

	return bucketName, filePath, nil
}

func (h *TaskHandler) writeStatus(ctx context.Context, bucketName, jobId, status string, extra map[string]interface{}) error {
	bucket := h.cfg.GcsClient.Bucket(bucketName)
	obj := bucket.Object("results/" + jobId + ".json")

	data := map[string]interface{}{
		"jobId":     jobId,
		"status":    status,
		"updatedAt": time.Now().Format(time.RFC3339),
	}
	for k, v := range extra {
		data[k] = v
	}

	bytes, err := json.Marshal(data)
	if err != nil {
		return err
	}

	w := obj.NewWriter(ctx)
	w.ContentType = "application/json"
	if _, err := w.Write(bytes); err != nil {
		w.Close()
		return err
	}
	return w.Close()
}

func (h *TaskHandler) handleInput(i image.Image) {
	// maybe sleep here to simulate long running task
	time.Sleep(time.Duration(h.cfg.HandleInputSleepSec) * time.Second)
}

func (h *TaskHandler) handleB64(w http.ResponseWriter, t TaskStruct) {
	h.log.Sugar().Debugf("handling b64 encoded input ...")

	reader := base64.NewDecoder(base64.StdEncoding, strings.NewReader(*t.B64Input))

	// In Go, image/png must be registered, we do it via side-effect import.
	// We imported _ "image/png" via side-effect import in Go or just use png.Decode.
	img, err := image.Decode(reader)
	if err != nil {
		h.log.Sugar().Errorf("error decoding image: %s", err)
		w.WriteHeader(http.StatusBadRequest)
		return
	}

	h.log.Sugar().Infof("Decoded image format %dx%d ...", img.Bounds().Dx(), img.Bounds().Dy())

	h.handleInput(img)

	w.WriteHeader(http.StatusOK)
}

func (h *TaskHandler) HealthCheckHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "OK")
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
			h.handleB64(w, t)
			return
		}

		if t.JobId == "" {
			h.log.Sugar().Errorf("jobId is required")
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		bucketName, objPath, err := h.parseBucketPath(t.Path)
		if err != nil {
			h.log.Sugar().Infof("Error parsing path %v: %v\n", t.Path, err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		ctx := context.TODO()

		// 1. Immediately write RUNNING status to GCS
		h.log.Sugar().Infof("Updating task status to RUNNING for jobId: %s", t.JobId)
		err = h.writeStatus(ctx, bucketName, t.JobId, "RUNNING", map[string]interface{}{
			"gcsPath":       t.Path,
			"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
		})
		if err != nil {
			h.log.Sugar().Errorf("Failed to write RUNNING status to GCS: %v", err)
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		// Simulated processing delay to make RUNNING state observable in UI
		h.log.Sugar().Infof("Simulating processing delay of %d seconds...", h.cfg.HandleInputSleepSec)
		time.Sleep(time.Duration(h.cfg.HandleInputSleepSec) * time.Second)

		// check bucket
		bucket := h.cfg.GcsClient.Bucket(bucketName)
		if bucket == nil {
			h.log.Sugar().Errorf("Bucket not found: %v\n", bucketName)
			h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
				"error":   fmt.Sprintf("Bucket not found: %s", bucketName),
				"gcsPath": t.Path,
			})
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		// check file
		file := bucket.Object(objPath)
		_, err = file.Attrs(ctx)
		if err != nil {
			if err == storage.ErrObjectNotExist {
				h.log.Sugar().Errorf("Object not found in bucket %v: %v\n", bucketName, objPath)
				h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
					"error":         fmt.Sprintf("Object not found: %s", t.Path),
					"gcsPath":       t.Path,
					"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
				})
				w.WriteHeader(http.StatusNotFound)
				return
			}

			h.log.Sugar().Errorf("error fetching object attrs: %v", err)
			h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
				"error":         fmt.Sprintf("Error accessing object: %v", err),
				"gcsPath":       t.Path,
				"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
			})
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		// 2. Download the image
		rc, err := file.NewReader(ctx)
		if err != nil {
			h.log.Sugar().Errorf("Failed to read GCS file: %v", err)
			h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
				"error":         fmt.Sprintf("Failed to read GCS file: %v", err),
				"gcsPath":       t.Path,
				"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
			})
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		defer rc.Close()

		imgBytes, err := ioutil.ReadAll(rc)
		if err != nil {
			h.log.Sugar().Errorf("Failed to read image bytes: %v", err)
			h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
				"error":         fmt.Sprintf("Failed to read image bytes: %v", err),
				"gcsPath":       t.Path,
				"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
			})
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		// 3. Decode image
		img, format, err := image.Decode(bytes.NewReader(imgBytes))
		if err != nil {
			h.log.Sugar().Errorf("Failed to decode image: %v", err)
			h.writeStatus(ctx, bucketName, t.JobId, "FAILED", map[string]interface{}{
				"error":         fmt.Sprintf("Failed to decode image: %v", err),
				"gcsPath":       t.Path,
				"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
			})
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		srcBounds := img.Bounds()
		srcW := srcBounds.Dx()
		srcH := srcBounds.Dy()
		h.log.Sugar().Infof("Successfully decoded image: format %s, %dx%d", format, srcW, srcH)

		// 4. Write final COMPLETED status JSON to GCS
		h.log.Sugar().Infof("Task COMPLETED for jobId: %s", t.JobId)
		err = h.writeStatus(ctx, bucketName, t.JobId, "COMPLETED", map[string]interface{}{
			"gcsPath":       t.Path,
			"width":         srcW,
			"height":        srcH,
			"format":        format,
			"thumbnailPath": "gs://" + bucketName + "/thumbs/" + t.JobId + ".png",
		})
		if err != nil {
			h.log.Sugar().Errorf("Failed to write COMPLETED status to GCS: %v", err)
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

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
