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
from transformers import AutoProcessor
from gcs_utils import download_model_config_from_gcs

logger = logging.getLogger("taskhandler_vllm.vllm_engine")

# Module-level singletons for engine and processor
_engine: Optional[AsyncLLMEngine] = None
_processor: Optional[Any] = None

def resolve_model_path(model_path: str) -> str:
    """
    Checks if model weights exist locally. If not (and it's not a GCS URI), 
    attempts to download them directly from Hugging Face Hub before engine startup.
    """
    if os.path.exists(model_path):
        logger.info(f"Using local model path: {model_path}")
        return model_path
        
    if model_path.startswith("gs://"):
        logger.info(f"Model path '{model_path}' is a GCS URI. Will load dynamically via streaming.")
        return model_path
        
    # Attempt HF Hub download (vLLM will consume the returned cache dir)
    logger.info(f"Model path '{model_path}' not found locally. Downloading from Hugging Face Hub...")
    try:
        local_dir = snapshot_download(repo_id=model_path)
        logger.info(f"Model downloaded successfully to Hugging Face cache: {local_dir}")
        return local_dir
    except Exception as e:
        logger.error(f"Failed to download model '{model_path}' from HF Hub: {e}")
        raise RuntimeError(f"Failed to resolve model path: {model_path}") from e

def init_vllm_engine(
    model_path: str,
    tensor_parallel_size: int = 1,
    pipeline_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.90,
    max_model_len: Optional[int] = None,
    dtype: str = "auto",
    trust_remote_code: bool = False
) -> None:
    """
    Initializes the vLLM AsyncLLMEngine and AutoProcessor as module-level singletons.
    Blocks the thread until the model is fully loaded into GPU memory.
    If no GPU is present or CUDA is misconfigured, this will crash the application.
    """
    global _engine, _processor
    if _engine is not None or _processor is not None:
        logger.warning("vLLM Engine/Processor already initialized. Re-initializing.")
        
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
        # Bypass the extremely slow 80-second torch.compile JIT phase for instant serverless cold starts
        enforce_eager=os.environ.get("VLLM_ENFORCE_EAGER", "true").lower() == "true",
        # Maximize GCS read throughput with 32 parallel download threads during weight streaming
        model_loader_extra_config='{"concurrency": 32}' if load_format == "runai_streamer" else None,
    )
    _engine = AsyncLLMEngine.from_engine_args(engine_args)
    
    # 4. Initialize AutoProcessor
    if model_path.startswith("gs://"):
        # For GCS paths, download only the small configuration/tokenizer files locally,
        # since HuggingFace AutoProcessor does not support direct gs:// URIs.
        local_config_dir = "/tmp/model_config"
        logger.info(f"Model is GCS path. Downloading configuration files to: {local_config_dir}...")
        download_model_config_from_gcs(model_path, local_config_dir)
        processor_load_path = local_config_dir
    else:
        processor_load_path = resolved_path

    logger.info(f"Loading AutoProcessor from: {processor_load_path}...")
    _processor = AutoProcessor.from_pretrained(processor_load_path)
    
    logger.info("vLLM AsyncLLMEngine and AutoProcessor initialized successfully.")

async def run_vllm_inference_internal(
    prompt: str,
    schema: dict,
    image: Image.Image,
    request_id: str
) -> dict:
    """
    Submits a request to the vLLM engine with guided decoding schema constraint.
    """
    global _engine, _processor
    if _engine is None or _processor is None:
        raise RuntimeError(
            "vLLM engine and processor are not initialized. "
            "Please call init_vllm_engine() at application startup."
        )
        
    structured_outputs = StructuredOutputsParams(json=schema)
    sampling_params = SamplingParams(
        temperature=0.0, # Deterministic JSON output
        max_tokens=1024,
        structured_outputs=structured_outputs
    )
    
    # Prepare chat messages for the vision-language model, putting the image BEFORE the text
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt}
            ]
        }
    ]
    
    # Use the model's official processor to apply its chat template.
    # This automatically positions the image tokens correctly and injects all special tokens.
    formatted_prompt = _processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    logger.info(f"Applied chat template. Formatted prompt length: {len(formatted_prompt)}")
    
    inputs = {
        "prompt": formatted_prompt,
        "multi_modal_data": {"image": image}
    }
    
    results_generator = _engine.generate(
        inputs,
        sampling_params=sampling_params,
        request_id=request_id
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
