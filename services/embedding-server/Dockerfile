# Embedding Server Dockerfile
# Generates embeddings from audio files and text queries

FROM python:3.10-slim

# For GPU support, use this base image instead:
# FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
# RUN apt-get update && apt-get install -y python3.10 python3-pip

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libsndfile1 \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create model cache directory
RUN mkdir -p /models

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the server
CMD ["python", "server.py"]
