# apps/worker/tasks/maintenance_tasks.py
import os
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from celery import shared_task

@shared_task(name="tasks.maintenance_tasks.sweep_stale_properties")
def sweep_stale_properties(days_old: int = 10): # 0 FOR TESTING
    """
    Scans the database for active properties older than 'days_old'.
    Automatically marks them as expired to prevent dead leads.
    """
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    # Calculate the exact cutoff timestamp
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    try:
        # Find all properties that are "active" but haven't been updated recently
        result = db["properties"].update_many(
            {
                "availability.status": "active",
                "updated_at": {"$lt": cutoff_date}
            },
            {
                "$set": {
                    "availability.status": "expired",
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        log_msg = f"[Midnight Sweeper] Success: Scanned inventory. Expired {result.modified_count} stale properties."
        print(log_msg)
        return log_msg

    except Exception as e:
        error_msg = f"[Midnight Sweeper] Error during execution: {str(e)}"
        print(error_msg)
        return error_msg


@shared_task(name="tasks.maintenance_tasks.sweep_inventory_freshness")
def sweep_inventory_freshness():
    """
    Queries properties with status 'ACTIVE' and transitions their status to 'UNVERIFIED'
    if they exceed their transaction/type-specific freshness thresholds.
    """
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    now = datetime.now(timezone.utc)
    cursor = db["properties"].find({"status": "ACTIVE"})
    
    modified_count = 0
    for prop in cursor:
        updated_at = prop.get("updated_at")
        if not updated_at:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
            
        age_days = (now - updated_at).days
        
        listing_type = prop.get("listing_type", "").lower()
        property_type = prop.get("property_type", "").lower()
        
        transition = False
        
        # Category A: If 'listing_type' is 'rent' and age > 7 days -> UNVERIFIED
        if listing_type == "rent" and age_days > 7:
            transition = True
        # Category B: If 'listing_type' is 'sale'/'buy' and property_type is 'flat'/'commercial'/'apartment' and age > 60 days -> UNVERIFIED
        elif listing_type in ["sale", "buy"] and property_type in ["flat", "commercial", "apartment"] and age_days > 60:
            transition = True
        # Category C: If 'listing_type' is 'sale'/'buy' and property_type is 'plot'/'land' and age > 90 days -> UNVERIFIED
        elif listing_type in ["sale", "buy"] and property_type in ["plot", "land"] and age_days > 90:
            transition = True
            
        if transition:
            current_confidence = prop.get("confidence_score", 100)
            new_confidence = max(0, current_confidence - 10)
            
            db["properties"].update_one(
                {"_id": prop["_id"]},
                {"$set": {
                    "status": "UNVERIFIED",
                    "availability_status": "stale",
                    "confidence_score": new_confidence,
                    "updated_at": now
                }}
            )
            modified_count += 1
            
            # Increment broker's expired properties
            broker_phone = prop.get("broker_phone")
            if not broker_phone:
                broker_phone = prop.get("source", {}).get("broker_phone")
                
            if broker_phone:
                # Upsert broker profile if not present
                db["broker_profiles"].update_one(
                    {"_id": broker_phone},
                    {
                        "$set": {
                            "phone": broker_phone,
                            "last_seen_at": now
                        },
                        "$setOnInsert": {
                            "name": f"Broker {broker_phone}",
                            "properties_posted": 0,
                            "verified_properties": 0,
                            "expired_properties": 0,
                            "reliability_score": 100
                        }
                    },
                    upsert=True
                )
                # Increment expired_properties
                db["broker_profiles"].update_one(
                    {"_id": broker_phone},
                    {
                        "$inc": {"expired_properties": 1},
                        "$set": {"last_seen_at": now}
                    }
                )
                # Recalculate reliability score
                broker = db["broker_profiles"].find_one({"_id": broker_phone})
                if broker:
                    verified = broker.get("verified_properties", 0)
                    posted = broker.get("properties_posted", 0)
                    divisor = posted if posted > 0 else 1
                    reliability_score = max(0, int((verified / divisor) * 100))
                    
                    db["broker_profiles"].update_one(
                        {"_id": broker_phone},
                        {"$set": {"reliability_score": reliability_score}}
                    )
            
    log_msg = f"[Freshness Sweeper] Completed. Transitioned {modified_count} stale listings to UNVERIFIED."
    print(log_msg)
    return log_msg