import io
import logging
import traceback
from typing import Any, Optional
from PIL import Image, UnidentifiedImageError
from vllm_engine import run_vllm_inference_internal

logger = logging.getLogger("taskhandler_vllm.pipeline")

def extract_image_properties(image: Image.Image) -> dict:
    """Helper Step 1: Extract resolution and format properties of the image."""
    width, height = image.size
    img_format = image.format or "UNKNOWN"
    return {
        "width": width,
        "height": height,
        "format": img_format.lower()
    }

async def run_pipeline(
    prompt: str,
    schema: dict,
    image_bytes: bytes,
    request_id: str
) -> dict:
    """
    Orchestrates the multi-step image analysis pipeline.
    1. Decodes image and extracts dimensions (width, height, format).
    2. Invokes vLLM for token-level guided structured analysis.
    
    Ensures any exception logs the full traceback to stdout for remote debugging.
    """
    try:
        # Step 1: Decode image and extract metadata properties
        logger.info("Pipeline Step 1: Decoding image and extracting properties...")
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()  # Force load image bytes to verify decodability
        except UnidentifiedImageError as uie:
            logger.error(f"Image decoding failed: {uie}")
            raise ValueError(f"Invalid or corrupt image format: {uie}") from uie
            
        img_props = extract_image_properties(image)
        logger.info(f"Extracted properties successfully: {img_props}")
        
        # Step 2: Invoke the model for structural analysis
        logger.info("Pipeline Step 2: Executing vLLM structured generation...")
        llm_analysis = await run_vllm_inference_internal(
            prompt=prompt,
            schema=schema,
            image=image,
            request_id=request_id
        )
        logger.info("Pipeline completed successfully.")
        
        # Combine Step 1 and Step 2 results
        return {
            **img_props,
            "llm_analysis": llm_analysis
        }
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        logger.error(traceback.format_exc())  # Print the full stack trace to the logs
        raise e
