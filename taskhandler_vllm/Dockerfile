FROM vllm/vllm-openai:v0.23.0

WORKDIR /app

# Install uv via pip for high-speed package installation
RUN pip install --no-cache-dir uv

# Install only our project-specific extra dependencies,
# leaving the pre-installed, optimized vLLM and PyTorch untouched.
# This prevents any dependency conflicts or driver version mismatches.
RUN uv pip install --system --no-cache-dir \
    "fastapi>=0.110.0" \
    "pydantic>=2.6.0" \
    "google-cloud-storage>=2.15.0" \
    "pillow>=10.2.0" \
    "runai-model-streamer"

# Copy all modular application code
COPY main.py constants.py gcs_utils.py vllm_engine.py pipeline.py task.py model.py ./

# Expose the same port as the original task handler
EXPOSE 8090

# Start FastAPI app
ENTRYPOINT ["python3", "main.py"]
