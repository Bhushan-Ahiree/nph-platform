# services/property/extractor.py
import httpx
import json

def extract_property_details(raw_message: str) -> dict:
    """
    Sends raw broker/owner property listings to local Llama 3.2.
    Forces extraction into the NPH Property V2 JSON schema.
    """
    
    # Using the proven Docker-to-Windows gateway
    ollama_url = "http://host.docker.internal:11434/api/generate"
    print(f"[Inventory AI] Parsing property message via {ollama_url}...")
    
    prompt = f"""
    You are an elite real estate data extraction AI for Nashik Property Hub.
    Extract the property details from the broker's message into STRICT JSON format.
    Do not include markdown, explanations, or conversational text. ONLY output the JSON object.

    Keys and constraints required:
    - title: string (Create a short, clean title, e.g., "2 BHK Apartment in Indira Nagar")
    - property_type: "apartment", "villa", "plot", "commercial" (default "apartment")
    - listing_type: "rent" or "buy" (extract based on context, default "rent")
    - city: "Nashik", "Pune", or "Mumbai" (default "Nashik" if unsure)
    - area: string (Extract the specific locality, e.g., "Indira Nagar", "College Road")
    - price: integer (Extract the monthly rent or total sale price. Strip commas/currency. Default 0)
    - deposit: integer (Extract deposit if mentioned. Default 0)
    - bhk: integer (Extract number of bedrooms. Default 0)
    - parking: boolean (true if parking is mentioned, else false)
    - furnishing: "unfurnished", "semi-furnished", "fully-furnished" (default "unfurnished")
    - preferred_tenant: "family", "bachelor", "any" (default "any")
    - broker_name: string (Extract the name of the person posting or to contact. Null if not found)
    - broker_phone: string (Extract the phone number. Null if not found)

    Broker Message: "{raw_message}"
    """
    
    payload = {
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        # 30-second timeout allows the GTX 1650 to process the payload
        with httpx.Client(timeout=30.0) as client:
            response = client.post(ollama_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            extracted_json = json.loads(result["response"])
            return extracted_json
            
    except Exception as e:
        print(f"[Inventory AI Error] Failed to parse property: {str(e)}")
        return {}