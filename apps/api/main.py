# apps/api/main.py
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from shared.utils.database import connect_to_mongo, close_mongo_connection, db
import logging
from apps.api.routers.system import router as system_router
from apps.api.routes.property import router as property_router
from apps.api.routes.auth import router as auth_router
import uuid
from fastapi.middleware.cors import CORSMiddleware
from apps.api.routers.lead import router as lead_router

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    try:
        if db.client is not None:
            await db.client.admin.command('ping')
            logger.info("Pinged MongoDB deployment. Connection verified!")
    except Exception as e:
        logger.error(f"Failed to ping MongoDB: {e}")
        
    yield 
    
    await close_mongo_connection()

app = FastAPI(
    title="NPH Property Intelligence Core",
    version="1.0.0",
    description="Core infrastructure for the NPH ecosystem",
    lifespan=lifespan
)

@app.middleware("http")
async def add_correlation_id_middleware(request: Request, call_next):
    """Intercepts incoming transactions and mounts a distinct tracking handle to the context."""
    correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = correlation_id
    return response

# Wire the routers up to the application EXACTLY ONCE
app.include_router(auth_router)       
app.include_router(property_router)   
app.include_router(system_router)     # FIXED: Only included here, duplicate removed from bottom
app.include_router(lead_router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NPH API Core",
        "database_connected": db.client is not None
    }