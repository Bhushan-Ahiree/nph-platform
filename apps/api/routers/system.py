# apps/api/routers/system.py
from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from motor.motor_asyncio import AsyncIOMotorClient
from apps.api.schemas.task_schemas import AnalyticsTaskTrigger
from celery import Celery
import os

router = APIRouter(prefix="/system", tags=["System Observability & Workers"])

# Environment Safe URL Resolution
MONGO_URL = os.getenv("MONGO_URL") or os.getenv("MONGO_URI") or "mongodb://localhost:27017"
REDIS_URL = os.getenv("REDIS_URL") or "redis://redis:6379/0"

# Initialize runtime communication clients for monitoring
celery_client = Celery("nph_worker_core", broker=REDIS_URL)
redis_client = Redis.from_url(REDIS_URL, socket_timeout=2)

@router.get("/health", status_code=status.HTTP_200_OK)
async def get_system_health():
    """Performs real-time parallel pings across MongoDB Atlas and Redis to verify infrastructure health."""
    health_status = {
        "status": "healthy",
        "infrastructure": {
            "mongodb_atlas": "unverified",
            "redis_cache": "unverified"
        }
    }
    
    # 1. Verify Redis Connection Integrity
    try:
        if redis_client.ping():
            health_status["infrastructure"]["redis_cache"] = "connected"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["infrastructure"]["redis_cache"] = f"failed: {str(e)}"

    # 2. Perform a REAL dynamic async ping against your MongoDB Atlas deployment
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        await mongo_client.admin.command('ping')
        health_status["infrastructure"]["mongodb_atlas"] = "connected"
        mongo_client.close()
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["infrastructure"]["mongodb_atlas"] = f"failed: {str(e)}"
    
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health_status)
        
    return health_status

@router.post("/trigger-analytics", status_code=status.HTTP_202_ACCEPTED)
async def trigger_background_analytics(payload: AnalyticsTaskTrigger):
    """Dispatches a micro-market aggregation calculations payload out of the API layer into the task worker queue."""
    try:
        # FIXED: Target the exact absolute name registered by the Celery decorator
        task_signature = celery_client.send_task(
            "calculate_locality_trends", 
            args=[payload.locality]
        )
        return {
            "message": "Heavy analytics calculation successfully offloaded to distributed background workers.",
            "task_id": task_signature.id,
            "target_locality": payload.locality,
            "status": "queued"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit task signature to background engine: {str(e)}"
        )

@router.get("/analytics/snapshot/{locality}", status_code=status.HTTP_200_OK)
async def get_locality_snapshot(locality: str):
    """Fetches a pre-computed micro-market snapshot instantly from the materialization layer cache."""
    try:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["nph_core"]
        collection = db["analytics_snapshots"]
        
        snapshot = await collection.find_one({"locality": locality}, {"_id": 0})
        client.close()
        
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No materialized snapshot found for locality: '{locality}'. Run POST /system/trigger-analytics first to compute."
            )
            
        return snapshot
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch materialized data from cluster cache: {str(e)}"
        )