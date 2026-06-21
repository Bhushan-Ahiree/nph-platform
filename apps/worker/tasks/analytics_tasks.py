# apps/worker/tasks/analytics_tasks.py
import time
import os
from datetime import datetime, timezone
from main import celery_app
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

# FIXED: Connection string fallback strategy targeting your active Atlas Cluster
MONGO_URL = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")

async def save_materialized_snapshot(locality: str, compiled_metrics: dict):
    """Asynchronously connects to your database cluster and atomic-upserts the aggregated snapshots."""
    print(f"[Database Connection Tracker] Initializing client session targeting cluster loop...")
    
    client = AsyncIOMotorClient(MONGO_URL)
    db = client["nph_core"]  # Targeted directly to your actual operational database name
    collection = db["analytics_snapshots"]
    
    snapshot_payload = {
        "locality": locality,
        "city": "Nashik",
        "average_price_sqft": compiled_metrics["average_price_sqft"],
        "total_active_listings": compiled_metrics["total_active_listings"],
        "market_velocity": compiled_metrics["market_velocity"],
        "last_updated": datetime.now(timezone.utc)
    }
    
    # Enforce idempotent atomic rules: update if matches locality, insert if new
    await collection.update_one(
        {"locality": locality},
        {"$set": snapshot_payload},
        upsert=True
    )
    client.close()
    print(f"[Database Connection Tracker] Cache sync complete. Connection safely closed.")

# FIXED: Explicit absolute naming overrides standard module folder path generation strings
@celery_app.task(
    name="calculate_locality_trends",
    bind=True,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True
)
def calculate_locality_trends(self, locality: str):
    """Pre-computes price distribution models and saves a materialized snapshot to MongoDB Atlas."""
    task_id = self.request.id
    print(f"[Analytics Worker] [{task_id}] Running micro-market aggregation loops for: {locality}")
    
    try:
        # Simulate heavy analytical calculation loops over thousands of regional listing data blocks
        time.sleep(3)
        
        compiled_metrics = {
            "average_price_sqft": 4850.0,
            "total_active_listings": 42,
            "market_velocity": "High"
        }
        
        # Orchestrate the async write transaction safely inside Celery's pool boundary
        asyncio.run(save_materialized_snapshot(locality, compiled_metrics))
        
        print(f"[Analytics Worker] [{task_id}] Snapshot materialized and cached successfully to Atlas for: {locality}")
        return {"locality": locality, "status": "materialized"}
        
    except Exception as exc:
        print(f"[Task Failure] [{task_id}] Processing state broken: {str(exc)}. Triggering retry...")
        raise exc