FROM vllm/vllm-openai:v0.23.0

WORKDIR /app

# Copy the high-performance 'uv' binary from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy and install requirements using uv
# We use --system because vLLM and its GPU/CUDA dependencies are installed 
# globally in the base image's Python environment.
COPY requirements.txt .
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Copy all modular application code
COPY main.py constants.py gcs_utils.py vllm_engine.py pipeline.py ./

# Expose the same port as the original task handler
EXPOSE 8090

# Start FastAPI app
ENTRYPOINT ["python3", "main.py"]
