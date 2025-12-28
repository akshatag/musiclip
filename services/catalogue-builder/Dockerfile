# Catalogue Builder Dockerfile
# Fetches music from Apple Music API and builds the catalogue

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for secrets
RUN mkdir -p /secrets

# Default command shows help
ENTRYPOINT ["python", "build_catalogue.py"]
CMD ["--help"]
