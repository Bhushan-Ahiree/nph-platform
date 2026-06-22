import os
import json
import re
import uuid
import httpx
from datetime import datetime, timezone
from celery import shared_task
from pymongo import MongoClient
from apps.worker.tasks.whatsapp_tasks import send_whatsapp_message

# MongoDB Setup
mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
client = MongoClient(mongo_url)
db = client["nph_core"]

LLAMA_URL = "http://host.docker.internal:11434/api/generate"
API_BASE_URL = "http://api:8000"

def get_or_create_lead(phone_number: str) -> dict:
    lead = db["leads"].find_one({"id": phone_number})
    if not lead:
        lead = {
            "id": phone_number,
            "status": "DISCOVERY",
            "requirements": {
                "city": None,
                "area": None,
                "bhk": None,
                "min_price": None,
                "max_price": None,
                "property_type": None,
                "listing_type": None
            },
            "last_properties_sent": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        db["leads"].insert_one(lead)
    return lead

def extract_facts_with_ai(conversation_history: list, current_requirements: dict) -> str:
    """Uses LLM ONLY for complex intent and fact extraction over complete conversation threads."""
    history_lines = []
    for msg in conversation_history:
        role = msg.get("role", "user").upper()
        content = msg.get("content", "")
        history_lines.append(f"{role}: {content}")
    thread_history = "\n".join(history_lines)

    prompt = f"""You are an expert Real Estate Assistant in Nashik.
Analyze the conversation thread history and the current known requirements of the lead to extract any newly mentioned property requirements.

Current Known Requirements:
{json.dumps(current_requirements, indent=2)}

Conversation Thread History:
{thread_history}

CRITICAL INSTRUCTIONS:
1. EXTRACT NEW/CORRECTED FACTS:
   Look for the following fields in the conversation:
   - 'city' (string, e.g. "Nashik", "Pune")
   - 'area' (string micro-market locality, e.g. "Indira Nagar", "Gangapur Road", "Wakad")
   - 'bhk' (integer bedroom count, e.g. 1, 2, 3)
   - 'min_price' (float/integer budget minimum, e.g. 10000.0)
   - 'max_price' (float/integer budget maximum, e.g. 15000.0)
   - 'property_type' (string: "apartment", "villa", "plot", "commercial")
   - 'listing_type' (string: "rent", "buy", "sale")

2. TRANSLATE & NORMALIZE:
   - The message may be in Marathi, Hindi, or Hinglish. Translate internally to English.
   - Convert budget numbers like "15k" or "20k" to 15000.0 or 20000.0.

3. PERSIST EXISTING KNOWLEDGE:
   - Do NOT drop or overwrite previously extracted requirements with null unless the user explicitly corrects or changes their preference in the text thread.
   - Return the merged/cumulative state of requirements.

4. CONVERSATIONAL REPLY:
   - If we are STILL missing 'area', 'bhk', or 'listing_type' in the final merged requirements, generate a friendly reply asking for ONE missing detail.
   - If we have all three ('area', 'bhk', 'listing_type'), set the reply_text strictly to "MATCH_READY".

Respond ONLY in valid JSON format:
{{
    "requirements": {{
        "city": "Nashik",
        "area": "Indira Nagar",
        "bhk": 2,
        "min_price": 8000.0,
        "max_price": 15000.0,
        "property_type": "apartment",
        "listing_type": "rent"
    }},
    "reply_text": "Friendly question text or MATCH_READY"
}}"""
    try:
        response = httpx.post(LLAMA_URL, json={"model": "llama3.2", "prompt": prompt, "stream": False, "format": "json"}, timeout=60.0)
        return response.json().get("response", "{}")
    except Exception as e:
        print(f"[AI Error] {str(e)}")
        fallback = {
            "requirements": {},
            "reply_text": "I am having trouble connecting to my brain right now."
        }
        return json.dumps(fallback)

def extract_selection_with_regex(text: str) -> list:
    """Uses deterministic Regex to instantly find option numbers."""
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

    # 1. Retrieve or create conversation document
    conv = db["conversations"].find_one({"phone": sender})
    if not conv:
        conv = {
            "lead_id": lead["id"],
            "phone": sender,
            "channel": "whatsapp",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "messages": []
        }
        db["conversations"].insert_one(conv)

    # 2. Append new user message to array and database
    new_message = {
        "role": "user",
        "content": text,
        "timestamp": datetime.now(timezone.utc)
    }
    db["conversations"].update_one(
        {"phone": sender},
        {
            "$push": {"messages": new_message},
            "$set": {"updated_at": datetime.now(timezone.utc)}
        }
    )
    conv["messages"].append(new_message)
    
    status = lead.get("status", "DISCOVERY")

    # ==========================================
    # STATE: PROPERTIES_SENT -> VISIT_REQUESTED
    # ==========================================
    if status == "PROPERTIES_SENT":
        selections = extract_selection_with_regex(text)
        
        if not selections:
            reply_text = "Could you please reply with the exact option number (like 1 or 2) you'd like to visit?"
            print(f"=== OUTBOUND TO {sender} ===")
            print(reply_text)
            send_whatsapp_message.delay(sender, reply_text)
            
            # Append assistant message to thread
            assistant_message = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc)
            }
            db["conversations"].update_one(
                {"phone": sender},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )
            return "State: Properties Sent. Clarification requested."

        sent_prop_ids = lead.get("last_properties_sent", [])
        visits_created = 0

        for sel in selections:
            idx = sel - 1
            if 0 <= idx < len(sent_prop_ids):
                target_prop_id = sent_prop_ids[idx]
                prop = db["properties"].find_one({"property_id": target_prop_id, "status": "ACTIVE"})
                
                if prop:
                    visit_payload = {
                        "lead_id": lead["id"],
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
            db["leads"].update_one(
                {"id": lead["id"]}, 
                {"$set": {"status": "VISIT_REQUESTED", "updated_at": datetime.now(timezone.utc)}}
            )
            reply_text = f"Great! I have logged a site visit request for {visits_created} propert(ies). Our ground team will call you shortly to schedule the exact time!"
            print(f"=== OUTBOUND TO {sender} ===")
            print(reply_text)
            send_whatsapp_message.delay(sender, reply_text)
            
            assistant_message = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc)
            }
            db["conversations"].update_one(
                {"phone": sender},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )
            return f"State: Visit Requested. Created {visits_created} visits."
        else:
            reply_text = "Unfortunately, that property just got rented or the number was invalid. Which active option did you want?"
            print(f"=== OUTBOUND TO {sender} ===")
            print(reply_text)
            send_whatsapp_message.delay(sender, reply_text)
            
            assistant_message = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc)
            }
            db["conversations"].update_one(
                {"phone": sender},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )
            return "Invalid selection or inactive property."

    # ==========================================
    # STATE: DISCOVERY / PARTIAL_REQUIREMENTS
    # ==========================================
    ai_response_str = extract_facts_with_ai(conv["messages"], lead["requirements"])
    try:
        ai_data = json.loads(ai_response_str)
    except:
        ai_data = {"requirements": {}, "reply_text": "Could you clarify that?"}

    new_facts = ai_data.get("requirements", {})
    reply_text = ai_data.get("reply_text", "")

    # Merge newly extracted facts into requirements
    if new_facts:
        for fact_key, fact_val in new_facts.items():
            if fact_val is not None:
                db["extracted_facts"].insert_one({
                    "lead_id": lead["id"],
                    "fact_type": fact_key,
                    "value": fact_val,
                    "source_message_id": msg_id,
                    "created_at": datetime.now(timezone.utc)
                })
                lead["requirements"][fact_key] = fact_val

    # Run state transitions evaluation
    reqs = lead["requirements"]
    has_core = bool(reqs.get("area") and reqs.get("bhk") and reqs.get("listing_type"))
    
    if lead.get("status", "DISCOVERY") in ["DISCOVERY", "PARTIAL_REQUIREMENTS"]:
        if has_core:
            lead["status"] = "MATCHABLE"
        else:
            lead["status"] = "PARTIAL_REQUIREMENTS"

    lead["updated_at"] = datetime.now(timezone.utc)
    db["leads"].update_one(
        {"id": lead["id"]},
        {"$set": {"requirements": lead["requirements"], "status": lead["status"], "updated_at": lead["updated_at"]}}
    )

    if lead["status"] != "MATCHABLE":
        print(f"=== OUTBOUND TO {sender} ===")
        print(reply_text)
        send_whatsapp_message.delay(sender, reply_text)
        
        assistant_message = {
            "role": "assistant",
            "content": reply_text,
            "timestamp": datetime.now(timezone.utc)
        }
        db["conversations"].update_one(
            {"phone": sender},
            {
                "$push": {"messages": assistant_message},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        return f"State: {lead['status']}. Asked for missing info."
    else:
        print(f"[State Machine] Lead {lead['id']} is MATCHABLE. Triggering Engine...")
        try:
            listing_type = reqs.get("listing_type", "rent").lower()
            if "rent" in listing_type:
                listing_type = "rent"
            else:
                listing_type = "sale"

            max_price = reqs.get("max_price") or 999999999
            
            search_url = f"{API_BASE_URL}/properties/search?limit=3&bhk={reqs['bhk']}&max_price={int(max_price)}&area={reqs['area']}"
            api_resp = httpx.get(search_url, timeout=10.0)
            matches = api_resp.json().get("data", [])
            
            # Fetch historically sent property IDs for this lead to filter out duplicates
            cursor = db["matches"].find({"lead_id": lead["id"]})
            historical_matches = list(cursor)
            
            sent_property_ids = set()
            for hm in historical_matches:
                sent_property_ids.update(hm.get("property_ids", []))

            # Filter out already sent property IDs
            fresh_matches = []
            for m in matches:
                prop_id = m.get("property_id")
                if prop_id and prop_id not in sent_property_ids:
                    fresh_matches.append(m)

            print(f"=== OUTBOUND TO {sender} ===")
            if fresh_matches:
                fresh_matches = fresh_matches[:3]
                matched_ids = [m["property_id"] for m in fresh_matches]
                
                # Save recommendation block to matches collection
                match_doc = {
                    "match_id": f"match_{uuid.uuid4().hex[:8]}",
                    "lead_id": lead["id"],
                    "property_ids": matched_ids,
                    "status": "SENT",
                    "generated_at": datetime.now(timezone.utc)
                }
                db["matches"].insert_one(match_doc)

                # Transition lead status to PROPERTIES_SENT
                db["leads"].update_one(
                    {"id": lead["id"]}, 
                    {"$set": {
                        "status": "PROPERTIES_SENT", 
                        "last_properties_sent": matched_ids,
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                
                recommendations = []
                recommendation_text = ""
                for idx, m in enumerate(fresh_matches, 1):
                    recommendations.append({
                        "lead_id": lead["id"],
                        "property_id": m["property_id"],
                        "score": m.get("match_score", 90),
                        "sent_at": datetime.now(timezone.utc)
                    })
                    recommendation_text += f"*{idx}. {m.get('bhk')}BHK in {m.get('area')}*\nRent: ₹{m.get('price')} | Deposit: ₹{m.get('rental_details', {}).get('deposit')}\n\n"
                
                db["recommendation_history"].insert_many(recommendations)
                
                reply_text = recommendation_text + "Reply with the option number (e.g. 1 or 2) to book a site visit!"
                print(reply_text)
                send_whatsapp_message.delay(sender, reply_text)
            else:
                reply_text = "I have all your requirements, but currently no active properties match. I'll notify you when one arrives."
                print(reply_text)
                send_whatsapp_message.delay(sender, reply_text)
                
            assistant_message = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc)
            }
            db["conversations"].update_one(
                {"phone": sender},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )
            return "State: Matchable. Properties Sent."
        except Exception as e:
            print(f"Matching Engine Failed: {str(e)}")
            return "Error during matching"