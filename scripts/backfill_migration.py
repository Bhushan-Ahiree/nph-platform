# scripts/backfill_migration.py
import os
import sys
from pymongo import MongoClient

def run_migration():
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI") or "mongodb://localhost:27017"
    print(f"Connecting to MongoDB at {mongo_url}...")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    try:
        # 1. Backfill leads with default lead_type and source
        print("Migrating leads: setting default lead_type='CLIENT' and source='whatsapp'...")
        leads_res = db.leads.update_many(
            {"lead_type": {"$exists": False}},
            {"$set": {"lead_type": "CLIENT", "source": "whatsapp"}}
        )
        print(f"Leads updated: {leads_res.modified_count}")

        # 2. Backfill properties with default ownership_type
        print("Migrating properties: setting default ownership_type='broker'...")
        props_res = db.properties.update_many(
            {"ownership_type": {"$exists": False}},
            {"$set": {"ownership_type": "broker"}}
        )
        print(f"Properties updated: {props_res.modified_count}")

        # 3. Backfill broker_profiles with verified flag
        print("Migrating broker profiles: setting default verified=False...")
        brokers_res = db.broker_profiles.update_many(
            {"verified": {"$exists": False}},
            {"$set": {"verified": False}}
        )
        print(f"Broker profiles updated: {brokers_res.modified_count}")

        print("🎉 Migration completed successfully!")

    except Exception as e:
        print(f"❌ Error during migration: {str(e)}")
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    run_migration()
