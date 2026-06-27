# scripts/backfill_lead_scores.py
from pymongo import MongoClient
from services.lead.scoring import calculate_priority_score, calculate_temperature
import os
import sys

def main():
    # Setup path so services can be imported
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI", "mongodb://localhost:27017")
    client = MongoClient(mongo_url)
    db = client["nph_core"]
    
    print("Starting Lead Scoring Backfill...")
    leads_updated = 0
    
    cursor = db["leads"].find({})
    for lead in cursor:
        score = calculate_priority_score(lead)
        temp = calculate_temperature(score)
        
        updates = {
            "priority_score": score,
            "lead_temperature": temp
        }
        
        # Add missing fields
        if "follow_up_count" not in lead:
            updates["follow_up_count"] = 0
        if "lead_type" not in lead:
            updates["lead_type"] = "CLIENT"
        if "source" not in lead:
            updates["source"] = "whatsapp"
            
        db["leads"].update_one(
            {"_id": lead["_id"]},
            {"$set": updates}
        )
        leads_updated += 1
        
    print(f"Backfill complete! Updated {leads_updated} leads.")

if __name__ == "__main__":
    main()
