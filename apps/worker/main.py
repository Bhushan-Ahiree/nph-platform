# apps/worker/main.py
import os
from celery import Celery

# Initialize the Celery Distributed Core pointing to our Redis container service instance
celery_app = Celery(
    "nph_worker_core",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0")
)

# Operational System Optimization Rules
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True
)

# FIXED: Explicitly register task modules via direct string imports
celery_app.conf.imports = (
    "tasks.ingestion_tasks",
    "tasks.analytics_tasks",
)