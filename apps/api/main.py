# apps/api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from shared.utils.database import connect_to_mongo, close_mongo_connection, db
import logging

from apps.api.routes.property import router as property_router
# NEW IMPORT: Pull the auth router directly
from apps.api.routes.auth import router as auth_router

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

# Wire the systems up to the application
app.include_router(auth_router)       # Authentication router registered
app.include_router(property_router)   # Property router registered

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NPH API Core",
        "database_connected": db.client is not None
    }