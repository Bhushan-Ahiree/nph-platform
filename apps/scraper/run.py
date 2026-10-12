# apps/scraper/run.py
import json
import os
import requests
from modules.extractor import PropertyExtractor
from modules.normalizer import PropertyNormalizer

# FIXED: Points exactly to the service key 'api' defined in docker-compose
API_BASE_URL = "http://api:8000" 

def authenticate_scraper() -> str:
    """Authenticates the scraper instance against the security core and secures a session token."""
    print("[Orchestrator] Requesting automated security handshake...")
    login_payload = {
        "username": os.getenv("SCRAPER_BOT_EMAIL", ""),
        "password": os.getenv("SCRAPER_BOT_PASSWORD", ""),
    }
    if not login_payload["username"] or not login_payload["password"]:
        print("[Security Error] SCRAPER_BOT_EMAIL / SCRAPER_BOT_PASSWORD are not set.")
        return ""
    try:
        response = requests.post(f"{API_BASE_URL}/auth/login", data=login_payload)
        if response.status_code == 200:
            print("[Orchestrator] Security handshake established token successfully.")
            return response.json()["access_token"]
        else:
            print(f"[Security Error] Handshake rejected: {response.text}")
            return ""
    except Exception as e:
        print(f"[Security Error] Core API is currently unreachable: {e}")
        return ""

def main():
    # 1. Load target configurations
    config_path = "source_configs/housing_nashik.json"
    with open(config_path, "r") as f:
        config = json.load(f)

    print(f"\n=== Starting Ingestion Pipeline Target: {config['source_name'].upper()} ===")

    # 2. Extract Raw Data
    extractor = PropertyExtractor(config)
    raw_listings = extractor.fetch_raw_listings()
    
    if not raw_listings:
        print("[Orchestrator] Zero records parsed. Exiting loop step.")
        return

    # 3. Authenticate with Core API
    token = authenticate_scraper()
    if not token:
        print("[Orchestrator Error] Execution terminated due to missing credentials.")
        return
        
    headers = {"Authorization": f"Bearer {token}"}
    success_count = 0
    duplicate_count = 0

    # 4. Normalize and Stream directly to API Endpoints
    normalizer = PropertyNormalizer()
    for item in raw_listings:
        # Calculate dynamic numeric area metrics
        built_up_area = normalizer.normalize_area(item["area_str"])
        
        normalized_payload = {
            "title": item["title"],
            "description": f"Automatically ingested listing from {config['source_name']}.",
            "property_type": "apartment",
            "listing_type": "sale",
            "city": config["target_city"],
            "area": item["locality"],
            "bhk": int(normalizer.normalize_bhk(item["bhk_str"])),
            "carpet_area_sqft": int(built_up_area * 0.8),
            "price": int(normalizer.normalize_price(item["price_str"])),
            "parking": False,
            "source": {
                "type": "scraping",
                "group_name": config["source_name"],
                "broker_name": "NPH Ingestion Bot",
                "broker_phone": "+919999999999"
            }
        }
        
        # Send the sanitized payload across the local docker network wire
        res = requests.post(f"{API_BASE_URL}/properties/", json=normalized_payload, headers=headers)
        
        if res.status_code == 201:
            success_count += 1
        elif res.status_code == 400:
            duplicate_count += 1
        else:
            print(f"[Streaming Error] Unexpected node reaction code {res.status_code}: {res.text}")

    print(f"\n=== Ingestion Run Completed ===")
    print(f"-> Successfully Normalized & Inserted: {success_count} Listings")
    print(f"-> Caught & Blocked by Duplicate Guardrails: {duplicate_count} Listings\n")

if __name__ == "__main__":
    main()