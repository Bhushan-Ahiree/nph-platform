# apps/worker/tasks/maintenance_tasks.py
import os
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from celery import shared_task

@shared_task(name="tasks.maintenance_tasks.sweep_stale_properties")
def sweep_stale_properties(days_old: int = 10): # 0 FOR TESTING
    """
    Scans the database for active properties older than 'days_old'.
    Automatically marks them as expired to prevent dead leads.
    """
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    # Calculate the exact cutoff timestamp
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    try:
        # Find all properties that are "active" but haven't been updated recently
        result = db["properties"].update_many(
            {
                "availability.status": "active",
                "updated_at": {"$lt": cutoff_date}
            },
            {
                "$set": {
                    "availability.status": "expired",
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        log_msg = f"[Midnight Sweeper] Success: Scanned inventory. Expired {result.modified_count} stale properties."
        print(log_msg)
        return log_msg

    except Exception as e:
        error_msg = f"[Midnight Sweeper] Error during execution: {str(e)}"
        print(error_msg)
        return error_msg