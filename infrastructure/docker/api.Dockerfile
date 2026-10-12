# infrastructure/docker/api.Dockerfile
# Shared image for the api, worker and scraper services.
FROM python:3.11-slim

# Prevent Python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install dependencies first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source so the image runs on its own; docker-compose also mounts it for live-reload
COPY . .
