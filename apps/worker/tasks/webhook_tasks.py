import os
import json
import re
import httpx
from datetime import datetime, timezone
from celery import shared_task
from pymongo import MongoClient

# MongoDB Setup
mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
client = MongoClient(mongo_url)
db = client["nph_core"]

LLAMA_URL = "http://host.docker.internal:11434/api/generate"
API_BASE_URL = "http://api:8000"

def get_or_create_lead(phone_number: str) -> dict:
    lead = db["leads"].find_one({"identities.value": phone_number})
    if not lead:
        lead = {
            "lead_id": f"lead_{phone_number[-6:]}",
            "status": "DISCOVERY",
            "identities": [{"type": "phone", "value": phone_number}],
            "requirements": {
                "bhk": None,
                "area": None, # Stored as raw string, API will handle slugification
                "budget_max": None,
                "tenant_type": None
            },
            "last_properties_sent": [], # Now strictly stores a list of property_ids (Strings)
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        db["leads"].insert_one(lead)
    return lead

def extract_facts_with_ai(lead_profile: dict, new_message: str) -> dict:
    """Uses LLM ONLY for complex intent and fact extraction."""
    prompt = f"""You are an expert Real Estate Assistant in Nashik.
Current Knowledge about Lead: {json.dumps(lead_profile['requirements'])}
Lead's New Message: "{new_message}"

CRITICAL INSTRUCTIONS:
1. TRANSLATE: The message may be in Marathi, Hindi, or Hinglish. Translate internally to English.
2. NORMALIZE NUMBERS: Convert abbreviations like "18k" to integer 18000. Convert "50k" to 50000.
3. EXTRACT NEW FACTS ONLY: 
   - 'bhk' (integer only, e.g., 2)
   - 'area' (string, e.g., "Indira Nagar")
   - 'budget_max' (integer only, e.g., 18000)
   - 'tenant_type' (string: "family", "bachelor", or "any")
4. CONVERSATION LOGIC: If we are STILL missing 'bhk', 'area', or 'budget_max' after combining knowledge, write a friendly reply asking for ONE missing detail. If we have all three, reply strictly with "MATCH_READY".

Respond ONLY in valid JSON:
{{
    "new_facts": {{ "bhk": 2, "area": "Indira Nagar", "budget_max": 18000, "tenant_type": "family" }},
    "reply_text": "MATCH_READY"
}}"""
    try:
        response = httpx.post(LLAMA_URL, json={"model": "llama3.2", "prompt": prompt, "stream": False, "format": "json"}, timeout=60.0)
        return response.json().get("response", "{}")
    except Exception as e:
        print(f"[AI Error] {str(e)}")
        return '{"new_facts": {}, "reply_text": "I am having trouble connecting to my brain right now."}'

def extract_selection_with_regex(text: str) -> list:
    """Uses deterministic Regex to instantly find option numbers (0ms, $0.00)."""
    # Finds all standalone digits in the text (e.g., "1 and 2" -> [1, 2])
    numbers = re.findall(r'\b\d+\b', text)
    return [int(num) for num in numbers]

@shared_task(name="tasks.webhook_tasks.process_incoming_message_event")
def process_incoming_message_event(event_id: str):
    event = db["webhook_events"].find_one({"event_id": event_id})
    if not event:
        return f"Error: Event '{event_id}' not found."

    sender = event.get("sender")
    text = event.get("payload", {}).get("text", "")
    msg_id = event.get("event_id", "msg_local_test")

    print(f"\n[Incoming Message] {sender}: {text}")

    lead = get_or_create_lead(sender)

    db["conversations"].insert_one({
        "lead_id": lead["lead_id"],
        "sender": sender, 
        "text": text, 
        "timestamp": datetime.now(timezone.utc)
    })
    
    status = lead.get("status", "DISCOVERY")

    # ==========================================
    # STATE: WAITING FOR USER TO PICK A PROPERTY
    # ==========================================
    if status == "PROPERTIES_SENT":
        selections = extract_selection_with_regex(text)
        
        if not selections:
            print(f"=== OUTBOUND TO {sender} ===")
            print("Could you please reply with the exact option number (like 1 or 2) you'd like to visit?")
            return "State: Properties Sent. Clarification requested."

        sent_prop_ids = lead.get("last_properties_sent", [])
        visits_created = 0

        for sel in selections:
            idx = sel - 1 # User says "1", which is array index 0
            if 0 <= idx < len(sent_prop_ids):
                target_prop_id = sent_prop_ids[idx]
                
                # Fetch fresh property data to ensure it hasn't been rented out in the last 10 minutes
                prop = db["properties"].find_one({"property_id": target_prop_id, "availability.status": "active"})
                
                if prop:
                    visit_payload = {
                        "lead_id": lead["lead_id"],
                        "property_id": prop["property_id"],
                        "broker_name": prop.get("source", {}).get("broker_name", "Unknown"),
                        "area": prop["area"]
                    }
                    try:
                        httpx.post(f"{API_BASE_URL}/site-visits/", json=visit_payload, timeout=10.0)
                        visits_created += 1
                    except Exception as e:
                        print(f"[API Error] Failed to create visit: {e}")
                else:
                    print(f"[Warning] Property {target_prop_id} is no longer active.")

        if visits_created > 0:
            # Shift state to VISIT_REQUESTED. Operations team takes over from here.
            db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"status": "VISIT_REQUESTED"}})
            print(f"=== OUTBOUND TO {sender} ===")
            print(f"Great! I have logged a site visit request for {visits_created} propert(ies). Our ground team will call you shortly to schedule the exact time!")
            return f"State: Visit Requested. Created {visits_created} visits."
        else:
            print(f"=== OUTBOUND TO {sender} ===")
            print("Unfortunately, that property just got rented or the number was invalid. Which active option did you want?")
            return "Invalid selection or inactive property."

    # ==========================================
    # STATE: DISCOVERY / PARTIAL REQUIREMENTS
    # ==========================================
    ai_response_str = extract_facts_with_ai(lead, text)
    try:
        ai_data = json.loads(ai_response_str)
    except:
        ai_data = {"new_facts": {}, "reply_text": "Could you clarify that?"}

    new_facts = ai_data.get("new_facts", {})
    reply_text = ai_data.get("reply_text", "")

    if new_facts:
        for fact_key, fact_val in new_facts.items():
            if fact_val:
                db["extracted_facts"].insert_one({
                    "lead_id": lead["lead_id"], "fact_type": fact_key,
                    "value": fact_val, "source_message_id": msg_id,
                    "created_at": datetime.now(timezone.utc)
                })
                lead["requirements"][fact_key] = fact_val
        
        lead["updated_at"] = datetime.now(timezone.utc)
        db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"requirements": lead["requirements"], "updated_at": lead["updated_at"]}})

    reqs = lead["requirements"]
    is_matchable = bool(reqs.get("bhk") and reqs.get("area") and reqs.get("budget_max"))

    if not is_matchable:
        db["leads"].update_one({"_id": lead["_id"]}, {"$set": {"status": "PARTIAL_REQUIREMENTS"}})
        print(f"=== OUTBOUND TO {sender} ===")
        print(reply_text)
        return "State: Partial. Asked for missing info."
    else:
        print(f"[State Machine] Lead {lead['lead_id']} is MATCHABLE. Triggering Engine...")
        try:
            # Enforcing the Area Slug & Availability check on the API side happens in the property_router
            search_url = f"{API_BASE_URL}/properties/search?limit=3&bhk={reqs['bhk']}&max_price={reqs['budget_max']}&area={reqs['area']}"
            api_resp = httpx.get(search_url, timeout=10.0)
            matches = api_resp.json().get("data", [])
            
            print(f"=== OUTBOUND TO {sender} ===")
            if matches:
                # 1. Extract just the IDs
                matched_ids = [m["property_id"] for m in matches]
                
                # 2. Update Lead Memory with IDs only
                db["leads"].update_one({"_id": lead["_id"]}, {"$set": {
                    "status": "PROPERTIES_SENT", 
                    "last_properties_sent": matched_ids
                }})
                
                # 3. Save Recommendation History for Analytics
                recommendations = []
                for idx, m in enumerate(matches, 1):
                    recommendations.append({
                        "lead_id": lead["lead_id"],
                        "property_id": m["property_id"],
                        "score": m.get("match_score", 90), # Defaulting to 90 until scoring logic is built
                        "sent_at": datetime.now(timezone.utc)
                    })
                    # Commission Shield Print
                    print(f"*{idx}. {m.get('bhk')}BHK in {m.get('area')}*")
                    print(f"Rent: ₹{m.get('price')} | Deposit: ₹{m.get('rental_details', {}).get('deposit')}\n")
                
                db["recommendation_history"].insert_many(recommendations)
                print("Reply with the number to book a site visit!")
            else:
                print("I have all your requirements, but currently no active properties match. I'll notify you when one arrives.")
                
            return "State: Matchable. Properties Sent."
        except Exception as e:
            print(f"Matching Engine Failed: {str(e)}")
            return "Error during matching"