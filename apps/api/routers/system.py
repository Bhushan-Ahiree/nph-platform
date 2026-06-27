# apps/api/routers/system.py
from fastapi import APIRouter, HTTPException, status
from redis import Redis
from apps.api.schemas.task_schemas import AnalyticsTaskTrigger
from shared.utils.database import db
from celery import Celery
import os

router = APIRouter(prefix="/system", tags=["System Observability & Workers"])

# Environment Safe URL Resolution
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

    # 2. Perform a REAL dynamic async ping against MongoDB Atlas via the shared singleton client
    try:
        if db.client is None:
            raise RuntimeError("MongoDB client not initialized")
        await db.client.admin.command('ping')
        health_status["infrastructure"]["mongodb_atlas"] = "connected"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["infrastructure"]["mongodb_atlas"] = f"failed: {str(e)}"

    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health_status)

    return health_status