# apps/worker/tasks/webhook_tasks.py
import os
import json
import httpx
from datetime import datetime, timezone
from celery import shared_task
from pymongo import MongoClient

# MongoDB Setup
mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
client = MongoClient(mongo_url)
db = client["nph_core"]

LLAMA_URL = "http://host.docker.internal:11434/api/generate"

def get_or_create_lead(phone_number: str) -> dict:
    """Fetches existing lead or creates a new one in the DISCOVERY state."""
    lead = db["leads"].find_one({"identities.value": phone_number})
    if not lead:
        lead = {
            "lead_id": f"lead_{phone_number[-6:]}",
            "status": "DISCOVERY",
            "identities": [{"type": "phone", "value": phone_number}],
            "requirements": {
                "bhk": None,
                "area": None,
                "budget_max": None,
                "tenant_type": None
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        db["leads"].insert_one(lead)
    return lead

def extract_facts_with_ai(lead_profile: dict, new_message: str) -> dict:
    """Uses Llama 3.2 to extract NEW facts, with strict normalization for Marathi/Hindi/Hinglish."""
    
    prompt = f"""You are an expert Real Estate Assistant in Nashik.
Current Knowledge about Lead: {json.dumps(lead_profile['requirements'])}
Lead's New Message: "{new_message}"

CRITICAL INSTRUCTIONS:
1. TRANSLATE: The message may be in Marathi, Hindi, or Hinglish (e.g., "pahije", "sathi", "parayant", "madhe"). Translate it internally to English before extracting.
2. NORMALIZE NUMBERS: Convert abbreviations like "18k" to integer 18000. Convert '50k' to 50000.
3. EXTRACT NEW FACTS ONLY: 
   - 'bhk' (integer only, e.g., 2)
   - 'area' (string, remove suffixes like 'la' or 'madhe', e.g., "College Road")
   - 'budget_max' (integer only, e.g., 18000)
   - 'tenant_type' (string: "family", "bachelor", or "any")
4. CONVERSATION LOGIC: If we are STILL missing 'bhk', 'area', or 'budget_max' after combining current knowledge and new facts, write a short, friendly reply asking for ONE missing detail. If we have all three, reply strictly with "MATCH_READY".

Respond ONLY in valid JSON format matching this exact structure:
{{
    "new_facts": {{ "bhk": 2, "area": "College Road", "budget_max": 18000, "tenant_type": "family" }},
    "reply_text": "MATCH_READY"
}}"""

    try:
        response = httpx.post(LLAMA_URL, json={
            "model": "llama3.2",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }, timeout=60.0)
        
        return response.json().get("response", "{}")
    except Exception as e:
        print(f"[AI Error] {str(e)}")
        return '{"new_facts": {}, "reply_text": "I am having trouble connecting to my brain right now."}'
    
@shared_task(name="tasks.webhook_tasks.process_incoming_message_event")
def process_incoming_message_event(event_id: str):
    # 0. Fetch the payload using the event_id from the API
    event = db["webhook_events"].find_one({"event_id": event_id})
    if not event:
        return f"Error: Event '{event_id}' not found in database."

    # Extract data from the fetched event
    sender = event.get("sender")
    text = event.get("payload", {}).get("text", "")
    msg_id = event.get("event_id", "msg_local_test")

    print(f"\n[Incoming Message] {sender}: {text}")

    # 1. Fetch Stateful Lead Profile FIRST
    lead = get_or_create_lead(sender)

    # 2. Save Raw Conversation WITH the correct lead_id
    db["conversations"].insert_one({
        "lead_id": lead["lead_id"],
        "sender": sender, 
        "text": text, 
        "timestamp": datetime.now(timezone.utc)
    })
    
    # 3. AI Fact Extraction (Incremental Enrichment)
    ai_response_str = extract_facts_with_ai(lead, text)
    try:
        ai_data = json.loads(ai_response_str)
    except:
        ai_data = {"new_facts": {}, "reply_text": "Could you clarify that?"}

    new_facts = ai_data.get("new_facts", {})
    reply_text = ai_data.get("reply_text", "")

    # 4. Save Facts for Traceability & Update Lead Profile
    if new_facts:
        for fact_key, fact_val in new_facts.items():
            if fact_val:
                # Save to Fact Store
                db["extracted_facts"].insert_one({
                    "lead_id": lead["lead_id"],
                    "fact_type": fact_key,
                    "value": fact_val,
                    "source_message_id": msg_id,
                    "created_at": datetime.now(timezone.utc)
                })
                # Update Lead Document
                lead["requirements"][fact_key] = fact_val
        
        # Save updated lead back to DB
        lead["updated_at"] = datetime.now(timezone.utc)
        db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"requirements": lead["requirements"], "updated_at": lead["updated_at"]}})

    # 5. STATE MACHINE EVALUATION
    reqs = lead["requirements"]
    is_matchable = bool(reqs.get("bhk") and reqs.get("area") and reqs.get("budget_max"))

    if not is_matchable:
        # State: PARTIAL_REQUIREMENTS
        db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"status": "PARTIAL_REQUIREMENTS"}})
        print(f"=== OUTBOUND TO {sender} ===")
        print(reply_text)
        return "State: Partial. Asked for missing info."

    else:
        # State: MATCHABLE -> Trigger Engine
        db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"status": "MATCHABLE"}})
        print(f"[State Machine] Lead {lead['lead_id']} is MATCHABLE. Triggering Engine...")
        
        # Call the existing search endpoint
        try:
            search_url = f"http://api:8000/properties/search?limit=3&bhk={reqs['bhk']}&max_price={reqs['budget_max']}&area={reqs['area']}"
            api_resp = httpx.get(search_url, timeout=10.0)
            matches = api_resp.json().get("data", [])
            
            print(f"=== OUTBOUND TO {sender} ===")
            if matches:
                print(f"Great news! I found {len(matches)} properties matching your 100% complete profile:\n")
                for idx, m in enumerate(matches, 1):
                    # Commission Shield
                    print(f"*{idx}. {m.get('bhk')}BHK in {m.get('area')}*")
                    print(f"Rent: ₹{m.get('price')} | Deposit: ₹{m.get('rental_details', {}).get('deposit')}\n")
                print("Reply with the number to book a site visit!")
            else:
                print("I have all your requirements, but currently no active properties match. I'll notify you when one arrives.")
                
            return "State: Matchable. Properties Sent."
            
        except Exception as e:
            print(f"Matching Engine Failed: {str(e)}")
            return "Error during matching"