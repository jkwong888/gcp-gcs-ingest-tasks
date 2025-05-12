import httpx
import asyncio
import os
import subprocess
from google.cloud import storage
import logging
import sys
import time
from PIL import Image
import io
import argparse
import urllib
import base64
import json

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# PNG Magic Number (8 bytes)
PNG_MAGIC_NUMBER = b'\x89PNG\r\n\x1a\n'
# IEND Chunk (bytes: 00 00 00 00 49 45 4E 44 AE 42 60 82)
# It's a 12-byte sequence: 4 bytes for length (0), 4 bytes for chunk type ('IEND'), 4 bytes for CRC.
PNG_IEND_CHUNK = b'\x00\x00\x00\x00IEND\xaeB`\x82'

def parse_gcs_url(gs_url: str) -> tuple[str | None, str | None]:
    """
    Correctly parses a Google Cloud Storage URL (gs://bucket/object/path)
    into its bucket name and object path using urllib.parse.

    Args:
        gs_url (str): The GCS URL string (e.g., 'gs://my-bucket/path/to/file.txt').

    Returns:
        tuple[str | None, str | None]: A tuple containing (bucket_name, object_path).
                                       Returns (None, None) if the URL is invalid or cannot be parsed.
    """
    if not gs_url.startswith("gs://"):
        logging.error(f"Invalid GCS URL scheme: '{gs_url}'. Must start with 'gs://'.")
        return None, None

    try:
        # Parse the URL into its components
        # The netloc will be the bucket name, and the path will be the object path.
        parsed_url = urllib.parse.urlparse(gs_url)

        bucket_name = parsed_url.netloc
        object_path = parsed_url.path.lstrip('/') # Remove leading slash if present

        if not bucket_name:
            logging.error(f"Invalid GCS URL: No bucket name found in '{gs_url}'.")
            return None, None

        if not object_path:
            object_path = None # Representing an object path as None if it's just a bucket URL

        logging.info(f"Parsed '{gs_url}' -> Bucket: '{bucket_name}', Path: '{object_path}'")
        return bucket_name, object_path
    except Exception as e:
        logging.error(f"An unexpected error occurred while parsing GCS URL '{gs_url}': {e}")
        return None, None

async def detect_png_stream(process_stdout_reader):
    """
    Asynchronously reads byte stream from subprocess stdout, detects PNGs, and extracts them.
    Yields complete PNG image bytes.
    """
    buffer = b''
    png_count = 0
    logging.info("Starting to asynchronously read subprocess stdout for PNGs...")

    try:
        while True:
            # Read a chunk of data from stdout asynchronously
            # This will await data without blocking the event loop
            chunk = await process_stdout_reader.read(65536) # Read 64KB chunks
            if not chunk:
                # EOF reached or pipe closed
                logging.info("Subprocess stdout pipe closed (EOF).")
                break

            buffer += chunk

            while True:
                # Try to find the magic number
                magic_index = buffer.find(PNG_MAGIC_NUMBER)

                if magic_index == -1:
                    # No magic number found in the current buffer.
                    # Keep enough data in the buffer to catch a magic number split across chunks.
                    if len(buffer) > len(PNG_MAGIC_NUMBER) * 2:
                        buffer = buffer[-len(PNG_MAGIC_NUMBER)*2:]
                    break # Go back to read more data

                logging.info(f"Found PNG magic number at index {magic_index}. Extracting image...")

                # We found the start of a PNG. Now find the end.
                # The current image starts at magic_index.
                current_image_data = buffer[magic_index:]

                # Find the IEND chunk relative to the start of the current image data
                # This is often the most challenging part for streamed image data
                iend_index_relative = current_image_data.find(PNG_IEND_CHUNK)

                if iend_index_relative == -1:
                    # IEND chunk not yet in buffer, need more data
                    # Shift buffer to start of potential image to avoid re-scanning old data
                    buffer = buffer[magic_index:]
                    break # Go back to read more data

                # Complete image found!
                image_end_index_in_buffer = magic_index + iend_index_relative + len(PNG_IEND_CHUNK)
                complete_image_bytes = buffer[magic_index:image_end_index_in_buffer]

                png_count += 1
                logging.info(f"Extracted PNG image {png_count}, size: {len(complete_image_bytes)} bytes")

                # Yield the complete image bytes
                yield complete_image_bytes

                # Remove the extracted image from the buffer
                buffer = buffer[image_end_index_in_buffer:]

    except asyncio.CancelledError:
        logging.warning("PNG detection task cancelled.")
    except Exception as e:
        logging.error(f"Error processing stdout for PNGs: {e}")


def upload_bytes_to_gcs_from_string(bucket_name: str, blob_name: str, data_bytes: bytes, content_type: str = 'application/octet-stream'):
    """
    Uploads bytes to a GCS blob using blob.upload_from_string().

    Args:
        bucket_name (str): The name of your GCS bucket.
        blob_name (str): The desired path/name for the object in the bucket (e.g., 'my-folder/my-file.txt').
        data_bytes (bytes): The raw bytes data to upload.
        content_type (str): The MIME type of the data (e.g., 'image/png', 'text/plain').
    Returns:
        bool: True if upload is successful, False otherwise.
    """
    try:
        client = storage.Client()
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Upload from a byte string
        blob.upload_from_string(data_bytes, content_type=content_type)

        logging.info(f"Successfully uploaded {len(data_bytes)} bytes to gs://{bucket_name}/{blob_name}")
        return True
    except Exception as e:
        logging.error(f"Failed to upload bytes to GCS: {e}")
        return False

async def async_upload_bytes_to_gcs(bucket_name: str, blob_name: str, data_bytes: bytes, content_type: str = 'application/octet-stream'):
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(
        None, # Use default thread pool executor
        upload_bytes_to_gcs_from_string, # The synchronous function
        bucket_name, blob_name, data_bytes, content_type
    )
    return success


async def async_send_bytes_to_handler(data_bytes: bytes, handler_url: str):
    """
    Sends an asynchronous POST request to the specified URL.

    Args:
        handler_url (str): The URL to send the POST request to.
        data_bytes (bytes): bytes to b64 encodeto handler.

    Returns:
        httpx.Response or None: The httpx Response object if successful, None otherwise.
    """
    headers = {"Content-Type": "application/json"} # Default for JSON payload
    
    encoded_base64_bytes = base64.b64encode(data_bytes)
    encoded_base64_str = encoded_base64_bytes.decode("utf-8")
    payload = {
        "b64input": encoded_base64_str,
    }
    timeout = 10

    # httpx.AsyncClient is recommended for making multiple requests
    # within the same application lifecycle for connection pooling and efficiency.
    # For a single request, you can use await httpx.post(...) directly.
    async with httpx.AsyncClient() as client:
        try:
            #logging.info(f"Sending POST request to: {handler_url} with payload: {payload}")
            response = await client.post(handler_url, json=payload, headers=headers, timeout=timeout)

            response.raise_for_status() # Raise an exception for 4xx/5xx responses

            logging.info(f"Request to {handler_url} succeeded (Status: {response.status_code})")
            logging.info(f"Response headers: {response.headers}")
            if len(response.content) > 0:
                logging.info(f"Response JSON: {response.json()}")
            return response

        except httpx.TimeoutException as e:
            logging.error(f"Request to {handler_url} timed out: {e}")
        except httpx.RequestError as e:
            logging.error(f"An error occurred while sending request to {handler_url}: {e}")
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error occurred for {e.request.url}: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")


async def send_png_to_api(png_detection_task, bucket_name: str = None, handler_url: str = None):
    extracted_count = 0
    async for image_bytes in png_detection_task:
        extracted_count += 1
        output_base_name = "keyframes/asdf"
        tasks = []
        try:
            # Optional: Process the image (e.g., open with Pillow, save to disk)
            image = Image.open(io.BytesIO(image_bytes))
            logging.info(f"Processing extracted PNG {extracted_count}: {image.size} {image.format}")
            if bucket_name is not None:
                tasks.append(asyncio.create_task(async_upload_bytes_to_gcs(bucket_name, f"{output_base_name}_frame_{extracted_count:05d}.png", image_bytes, "image/png")))
            if handler_url is not None:
                tasks.append(asyncio.create_task(async_send_bytes_to_handler(image_bytes, handler_url)))

        except Exception as e:
            logging.error(f"Failed to process extracted PNG {extracted_count}: {e}")
    
    await asyncio.gather(*tasks)


async def consume_stderr(process_stderr_reader):
    logging.info("Stderr consumer started.")
    full_stderr = b''
    try:
        while True:
            line = await process_stderr_reader.readline() # Or read(n) for binary output
            if not line:
                break
            full_stderr += line
            sys.stderr.buffer.write(line) # Write to console immediately
            sys.stderr.buffer.flush()
    except asyncio.CancelledError:
        logging.warning("Stderr consumer cancelled.")
    except Exception as e:
        logging.error(f"Error in stderr consumer: {e}")
    finally:
        return full_stderr

async def process_gcs_video_with_ffmpeg_async(bucket_name: str, object_name: str, handler_url: str):
    """
    Asynchronously reads an MP4 file from Google Cloud Storage and pipes it to FFmpeg.
    """
    logging.info(f"Starting async processing for gs://{bucket_name}/{object_name}")

    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob(object_name)

    # Prepare FFmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-i", "pipe:0",
        "-vf", "select=eq(pict_type\,I)",
        "-vsync", "vfr",
        "-f", "image2pipe",
        "-vcodec", "png",
        "-"
    ]

    logging.info(f"FFmpeg command: {' '.join(ffmpeg_command)}")

    process = None # Initialize process to None
    gcs_reader = None

    # Create a streaming reader for the GCS object
    # blob.open('rb') returns a file-like object that asyncio can wrap
    blob.reload()
    gcs_reader = blob.open('rb')
    logging.info(f"Successfully opened GCS object reader: gs://{bucket_name}/{object_name}: {blob.size} bytes")

    # Start FFmpeg process asynchronously
    process = await asyncio.create_subprocess_exec(
        *ffmpeg_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    logging.info(f"FFmpeg process started asynchronously with pid {process.pid}. Piping GCS data...")

    # Asynchronously pipe GCS data to FFmpeg's stdin
    # asyncio.to_thread is used because gcs_reader.read() is a blocking I/O operation.
    # For true async GCS reads, you'd need an async GCS client library
    # or to implement a custom async reader for blob.download_as_bytes_async().
    async def pipe_data():
        total = 0
        while True:
            chunk = await asyncio.to_thread(gcs_reader.read, 65536) # Read larger chunks
            if not chunk:
                break
            process.stdin.write(chunk) # Write is non-blocking in asyncio pipe
            total += 1
            if total % 256 == 0:
                logging.info(f"wrote {65536 * total} bytes to stdin")
                pass
            await process.stdin.drain() # Ensure data is written (handle backpressure)
        process.stdin.close()
        logging.info("Finished piping GCS data to FFmpeg stdin.")

    # Run the piping and process waiting concurrently
    # (await process.wait() also waits for stdin to be closed implicitly if nothing is written)
    png_detection = detect_png_stream(process.stdout)
    pipe_task = asyncio.create_task(pipe_data())
    png_detection_task = asyncio.create_task(send_png_to_api(png_detection, handler_url=handler_url))
    stderr_task = asyncio.create_task(consume_stderr(process.stderr))

    try:
        # Wait for all tasks to complete
        await asyncio.gather(
            pipe_task, 
            png_detection_task, 
            stderr_task,
            asyncio.create_task(process.wait()))
    except FileNotFoundError:
        logging.error("FFmpeg command not found. Please ensure FFmpeg is installed and in your system's PATH.")
        return False
    except asyncio.CancelledError:
        logging.warning("Async FFmpeg processing was cancelled.")
        if process and process.returncode is None: # If process is still running
            process.terminate()
            await process.wait() # Wait for termination
        return False
    except Exception as e:
        logging.error(f"An error occurred during FFmpeg processing: {e}")
        return False
    finally:
        if gcs_reader:
            gcs_reader.close() # Ensure the GCS reader is closed

        if process.returncode != 0:
            logging.error(f"FFmpeg exited with non-zero status {process.returncode}")
            #logging.error(f"FFmpeg Stdout:\n{stdout_data}")
            #logging.error(f"FFmpeg Stderr:\n{stderr_data}")
            return False
        else:
            logging.info("FFmpeg finished successfully.")
            #logging.info(f"FFmpeg Stdout:\n{stdout_data}")
            #logging.info(f"FFmpeg Stderr:\n{stderr_data}")
            return True


async def main_async(args):
    # Example with a timeout
    try:
        bucket, path = parse_gcs_url(args.gcs_path)

        await asyncio.wait_for(
            process_gcs_video_with_ffmpeg_async(
                bucket_name=bucket,
                object_name=path,
                handler_url = args.handler_url
            ),
            timeout=600 # 10 minutes timeout
        )
        logging.info("Video processing workflow completed successfully.")
    except asyncio.TimeoutError:
        logging.error("Video processing workflow timed out.")
    except Exception as e:
        logging.error(f"An error occurred during main async execution: {e}")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="tool to use ffmpeg to extract keyframes"
    )

    parser.add_argument(
        "gcs_path",
        type=str,
        help="Path to video file e.g. gs://bucket/path/to/object",
    )

    parser.add_argument(
        "handler_url",
        type=str,
        help="URL to image handler",
    )

    args = parser.parse_args()

    # Run the async main function
    asyncio.run(main_async(args))



