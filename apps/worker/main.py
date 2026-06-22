# apps/worker/main.py
import os
from celery import Celery
from celery.schedules import crontab

# Initialize the Celery Distributed Core
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
    broker_connection_retry_on_startup=True,
    
    # ADDED: The central beat schedule
    beat_schedule={
        'sweep-stale-inventory-nightly': {
            'task': 'tasks.maintenance_tasks.sweep_stale_properties',
            'schedule': crontab(hour=2, minute=0), # 1-MINUTE TEST MODE
        },
        'sweep-inventory-freshness-loop': {
            'task': 'tasks.maintenance_tasks.sweep_inventory_freshness',
            'schedule': crontab(minute='*/5'),
        },
    }
)

# FIXED: Explicitly register task modules via direct string imports
celery_app.conf.imports = (
    "tasks.ingestion_tasks",
    "tasks.analytics_tasks",
    "tasks.webhook_tasks",
    "tasks.maintenance_tasks", # ADDED!
    "tasks.whatsapp_tasks",
)