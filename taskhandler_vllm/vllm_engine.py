import os
import logging
from typing import Any, Optional
from PIL import Image

# Import vLLM and HuggingFace strictly as top-level imports
# If they are missing or if CUDA drivers are misconfigured, the app will fail fast on startup.
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm.sampling_params import SamplingParams, StructuredOutputsParams
from huggingface_hub import snapshot_download

logger = logging.getLogger("taskhandler_vllm.vllm_engine")


def resolve_model_path(model_path: str) -> str:
    """
    Checks if model weights exist locally. If not (and it's not a GCS URI), 
    attempts to download them directly from Hugging Face Hub before engine startup.
    """
    if model_path.startswith("gs://"):
        return model_path

    if not os.path.exists(model_path):
        logger.info(f"Model path '{model_path}' not found locally. Triggering explicit Hugging Face Hub download...")
        try:
            downloaded_dir = snapshot_download(repo_id=model_path)
            logger.info(f"Model successfully downloaded from Hugging Face Hub to: {downloaded_dir}")
            return downloaded_dir
        except Exception as e:
            logger.error(f"Failed to download model '{model_path}' from Hugging Face Hub: {e}")
            raise e
    
    return model_path


def init_vllm_engine(
    model_path: str,
    tensor_parallel_size: int = 1,
    pipeline_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.90,
    max_model_len: Optional[int] = None,
    dtype: str = "auto",
    trust_remote_code: bool = False
) -> AsyncLLMEngine:
    """
    Initializes the vLLM AsyncLLMEngine. Resolves paths and GCS streamers.
    Blocks the thread until the model is fully loaded into GPU memory.
    If no GPU is present or CUDA is misconfigured, this will crash the application.
    """
    # 1. Resolve local/HF model path
    resolved_path = resolve_model_path(model_path)
    
    # 2. Determine load format (GCS Streamer vs Standard Auto)
    if resolved_path.startswith("gs://"):
        logger.info(f"MODEL_PATH is a GCS URI ({resolved_path}). Enabling Run:ai Model Streamer.")
        load_format = "runai_streamer"
    else:
        logger.info(f"MODEL_PATH is a local path ({resolved_path}). Using standard 'auto' load format.")
        load_format = "auto"

    # 3. Initialize AsyncLLMEngine (strictly, no fallback)
    logger.info("Initializing vLLM AsyncLLMEngine...")
    engine_args = AsyncEngineArgs(
        model=resolved_path,
        load_format=load_format,
        tensor_parallel_size=tensor_parallel_size,
        pipeline_parallel_size=pipeline_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        dtype=dtype,
        trust_remote_code=trust_remote_code,
    )
    engine = AsyncLLMEngine.from_engine_args(engine_args)
    logger.info("vLLM AsyncLLMEngine initialized successfully.")
    return engine


async def run_vllm_inference_internal(
    engine: AsyncLLMEngine,
    prompt: str,
    schema: dict,
    image: Image.Image,
    request_id: str
) -> dict:
    """
    Submits a request to the vLLM engine with guided decoding schema constraint.
    """
    structured_outputs = StructuredOutputsParams(json=schema)
    sampling_params = SamplingParams(
        temperature=0.0, # Deterministic JSON output
        max_tokens=1024,
        structured_outputs=structured_outputs
    )
    
    results_generator = engine.generate(
        prompt=prompt,
        sampling_params=sampling_params,
        request_id=request_id,
        multi_modal_data={"image": image}
    )
    
    final_output = None
    async for request_output in results_generator:
        final_output = request_output
        
    if final_output and final_output.outputs:
        generated_text = final_output.outputs[0].text
        logger.info(f"Model generated text: {generated_text}")
        try:
            import json
            return json.loads(generated_text)
        except json.JSONDecodeError as je:
            logger.error(f"Failed to parse generated text as JSON: {je}. Text: {generated_text}")
            raise ValueError(f"Model did not return valid JSON: {je}")
    else:
        raise ValueError("No output received from vLLM engine")
