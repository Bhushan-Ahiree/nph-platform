# shared/utils/database.py
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging

logger = logging.getLogger("uvicorn.error")

class Database:
    client: AsyncIOMotorClient = None

db = Database()

async def connect_to_mongo():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        logger.error("MONGO_URI environment variable is missing!")
        return
    
    db.client = AsyncIOMotorClient(mongo_uri)
    logger.info("Successfully connected to MongoDB Atlas.")

async def close_mongo_connection():
    if db.client:
        db.client.close()
        logger.info("Closed MongoDB Atlas connection.")