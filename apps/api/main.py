# apps/api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from shared.utils.database import connect_to_mongo, close_mongo_connection, db
import logging
from shared.schemas.property import PropertyCreate
from datetime import datetime, timezone
import uuid

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    await connect_to_mongo()
    # Ping the database to verify the connection is actually working
    try:
        if db.client is not None:
            await db.client.admin.command('ping')
            logger.info("Pinged MongoDB deployment. Connection verified!")
    except Exception as e:
        logger.error(f"Failed to ping MongoDB: {e}")
        
    yield # The API runs here
    
    # Shutdown logic
    await close_mongo_connection()

app = FastAPI(
    title="NPH Property Intelligence Core",
    version="1.0.0",
    description="Core infrastructure for the NPH ecosystem",
    lifespan=lifespan
)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NPH API Core",
        "database_connected": db.client is not None
    }
    

@app.post("/properties", response_model=dict)
async def create_property(property_in: PropertyCreate):
    # This is a stub route. We will add the actual MongoDB insertion next.
    new_property = property_in.model_dump()
    
    # Add our internal tracking fields
    new_property["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"
    new_property["created_at"] = datetime.now(timezone.utc)
    new_property["updated_at"] = datetime.now(timezone.utc)
    
    return {
        "message": "Schema validated successfully!",
        "data": new_property
    }