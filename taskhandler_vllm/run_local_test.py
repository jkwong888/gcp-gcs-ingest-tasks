#!/usr/bin/env python3
#
# Local Smoke Test Script for vLLM Task Handler
#
# Usage:
#   1. Make sure the task handler is running locally:
#      python3 main.py (runs in mock mode by default if vLLM is not installed)
#   2. Run this script:
#      ./run_local_test.py --image /path/to/my/photo.jpg
#

import sys
import os
import base64
import argparse
import json

# We import urllib.request instead of requests to avoid requiring third-party libraries for testing!
import urllib.request
import urllib.error

def main():
    parser = argparse.ArgumentParser(description="Smoke test the running vLLM Task Handler")
    parser.add_argument("--image", type=str, help="Path to a local image file to process (will be sent as base64)")
    parser.add_argument("--gcs-path", type=str, help="GCS URI (gs://bucket/image.png) to process")
    parser.add_argument("--job-id", type=str, default="test-job-101", help="Mock Job ID for GCS status file name")
    parser.add_argument("--url", type=str, default="http://localhost:8090/", help="URL of the running task handler")
    
    args = parser.parse_args()
    
    if not args.image and not args.gcs_path:
        print("ERROR: You must specify either --image (for local files) or --gcs-path (for GCS objects).")
        parser.print_help()
        sys.exit(1)
        
    payload = {
        "jobId": args.job_id
    }
    
    if args.image:
        if not os.path.exists(args.image):
            print(f"ERROR: Local image file '{args.image}' not found.")
            sys.exit(1)
            
        print(f"Reading local image '{args.image}' and encoding to base64...")
        try:
            with open(args.image, "rb") as f:
                img_bytes = f.read()
                b64_data = base64.b64encode(img_bytes).decode("utf-8")
                payload["b64input"] = b64_data
        except Exception as e:
            print(f"ERROR: Failed to read/encode local image: {e}")
            sys.exit(1)
    else:
        print(f"Using GCS path: {args.gcs_path}")
        payload["gcsPath"] = args.gcs_path

    # Send POST request
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        args.url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    print(f"Sending POST request to {args.url} with payload keys: {list(payload.keys())} ...")
    try:
        # vLLM model loading could cause first request to take a moment, setting timeout to 300s
        with urllib.request.urlopen(req, timeout=300) as response:
            res_data = response.read().decode("utf-8")
            print(f"\n[SUCCESS] HTTP Status Code: {response.status}")
            try:
                parsed_res = json.loads(res_data)
                print("Response JSON:")
                print(json.dumps(parsed_res, indent=2))
            except Exception:
                print("Response Text:")
                print(res_data)
    except urllib.error.HTTPError as e:
        print(f"\n[ERROR] HTTP Error occurred. Status: {e.code}")
        try:
            err_data = e.read().decode("utf-8")
            parsed_err = json.loads(err_data)
            print("Error Details:")
            print(json.dumps(parsed_err, indent=2))
        except Exception:
            print(f"Error Message: {e.reason}")
    except urllib.error.URLError as e:
        print(f"\n[ERROR] Failed to reach the server at {args.url}. Is it running?")
        print(f"Reason: {e.reason}")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")

if __name__ == "__main__":
    main()
