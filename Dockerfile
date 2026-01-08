# -------------------------
# 1. Base image
# -------------------------
FROM python:3.12-slim AS base

# Prevent Python from writing pyc files & enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies your app may need
# (libpq for Postgres, gcc for any compiled deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# -------------------------
# 2. Copy the application
# -------------------------
COPY . .

# -------------------------
# 3. Install Python dependencies
# -------------------------
RUN pip install --upgrade pip \
 && pip install --no-cache-dir .

# Default environment variables
ENV PORT=8000 \
    AGENT_OLLAMA_BASE_URL=http://ollama:11434 \
    AGENT_OLLAMA_MODEL=phi4-mini \
    AGENT_AUTO_PULL_OLLAMA_MODELS=true

# Expose FastAPI port
EXPOSE 8000

# -------------------------
# 4. Startup command
# -------------------------
# This script:
# • runs your Ollama preflight check
# • then starts uvicorn
CMD ["python", "run_server.py"]
