# # apps/api/main.py
# from fastapi import FastAPI
# from contextlib import asynccontextmanager
# from shared.utils.database import connect_to_mongo, close_mongo_connection, db
# import logging
# from shared.schemas.property import PropertyCreate
# from datetime import datetime, timezone
# import uuid

# logger = logging.getLogger("uvicorn.error")

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Startup logic
#     await connect_to_mongo()
#     # Ping the database to verify the connection is actually working
#     try:
#         if db.client is not None:
#             await db.client.admin.command('ping')
#             logger.info("Pinged MongoDB deployment. Connection verified!")
#     except Exception as e:
#         logger.error(f"Failed to ping MongoDB: {e}")
        
#     yield # The API runs here
    
#     # Shutdown logic
#     await close_mongo_connection()

# app = FastAPI(
#     title="NPH Property Intelligence Core",
#     version="1.0.0",
#     description="Core infrastructure for the NPH ecosystem",
#     lifespan=lifespan
# )

# @app.get("/")
# async def root():
#     return {
#         "status": "online",
#         "service": "NPH API Core",
#         "database_connected": db.client is not None
#     }
    


# apps/api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from shared.utils.database import connect_to_mongo, close_mongo_connection, db
import logging

# CHANGE THIS LINE: Explicitly import the router object directly from the file
from apps.api.routes.property import router as property_router

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

# CHANGE THIS LINE: Pass the cleanly imported property_router
app.include_router(property_router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NPH API Core",
        "database_connected": db.client is not None
    }