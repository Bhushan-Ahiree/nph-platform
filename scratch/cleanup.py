import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("d:\\nph-platform\\.env")

async def main():
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")
    if not mongo_uri:
        print("MONGO_URI not found in env.")
        return
        
    client = AsyncIOMotorClient(mongo_uri)
    db = client.get_default_database()
    result = await db.leads.delete_many({"id": "918888888888", "status": "DISCOVERY"})
    print(f"Deleted {result.deleted_count} stale duplicate leads.")

if __name__ == "__main__":
    asyncio.run(main())
