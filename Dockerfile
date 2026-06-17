# Dockerfile
FROM python:3.11-slim

# Install uv for lightning-fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HERMIFY_HOME=/data/.hermify

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies and the package itself
RUN uv sync --frozen

# Expose the port HF Spaces expects
EXPOSE 7860

# Run the CLI directly in HTTP mode
# We use /data/.hermify so we can mount a persistent volume later if needed
CMD ["uv", "run", "hermify", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "7860"]