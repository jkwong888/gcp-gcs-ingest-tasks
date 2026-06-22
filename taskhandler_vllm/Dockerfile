FROM vllm/vllm-openai:v0.23.0

WORKDIR /app

# Copy the high-performance 'uv' binary from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency definitions and lock files, then sync them globally using uv
# We use --system because vLLM and its GPU/CUDA dependencies are installed 
# globally in the base image's Python environment. We use --no-dev to exclude pytest.
COPY pyproject.toml uv.lock ./
RUN uv sync --system --no-dev --no-cache --inexact

# Copy all modular application code
COPY main.py constants.py gcs_utils.py vllm_engine.py pipeline.py task.py ./

# Expose the same port as the original task handler
EXPOSE 8090

# Start FastAPI app
ENTRYPOINT ["python3", "main.py"]
