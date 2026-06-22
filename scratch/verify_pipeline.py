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
    
    print("--- CORE SUPPLY CHECK ---")
    new_props_cursor = db.properties.find().sort("created_at", -1).limit(5)
    new_props = await new_props_cursor.to_list(length=5)
    for p in new_props:
        print(f"ID: {p.get('_id') or p.get('id')}, BHK: {p.get('bhk')}, Area: {p.get('area')}, Price: {p.get('price')}, Status: {p.get('availability_status')}, Sources Count: {len(p.get('sources', []))}")
        
    print("\n--- SOURCE LEDGER CHECK ---")
    brokers_cursor = db.broker_profiles.find().sort("properties_posted", -1).limit(5)
    brokers = await brokers_cursor.to_list(length=5)
    for b in brokers:
        print(f"Broker ID: {b.get('broker_id') or b.get('_id')}, Name: {b.get('name') or b.get('phone')}, Properties Posted: {b.get('properties_posted') or b.get('properties_count') or 0}, Reliability: {b.get('reliability_score') or 'N/A'}")

if __name__ == "__main__":
    asyncio.run(main())
