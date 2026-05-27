# apps/worker/main.py
from celery import Celery
import os

# Ensure REDIS_URL falls back to container networks cleanly
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "nph_worker_core",
    broker=REDIS_URL,
    backend=REDIS_URL,
    # FIXED: Explicitly tell Celery to import and register your analytics module on boot
    include=["tasks.analytics_tasks"]
)

# Optional configuration settings to optimize task execution
celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
)