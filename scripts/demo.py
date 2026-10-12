# scripts/demo.py — end-to-end demo: send the synthetic WhatsApp export to the API, wait for the
# worker to process it, then print the structured listings it produced.
# Usage (stack running):  python scripts/demo.py
import os
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

API_URL = os.getenv("DEMO_API_URL", f"http://localhost:{os.getenv('API_PORT', '8000')}")
SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "samples", "sample_whatsapp_dump.txt")
GROUP_NAME = "Sample Nashik Property Group"
TIMEOUT_SECONDS = 120


def fetch_listings(client: httpx.Client) -> list:
    return client.get(f"{API_URL}/properties/", params={"limit": 50}).json()


def main():
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        raw_text = f.read()

    with httpx.Client(timeout=30.0) as client:
        before = len(fetch_listings(client))

        print(f"1. Sending {len(raw_text)} chars of raw WhatsApp text to POST /properties/raw-chunk")
        resp = client.post(f"{API_URL}/properties/raw-chunk", json={"source_group": GROUP_NAME, "raw_text": raw_text})
        body = resp.json()
        print(f"   -> {resp.status_code} {body.get('status')}: {body.get('message')}")
        listings, deadline, stable_polls = [], time.time() + TIMEOUT_SECONDS, 0
        if body.get("status") == "duplicate_skipped":
            print("   (Already ingested earlier — showing existing listings.)")
            listings, deadline = fetch_listings(client), 0
        else:
            print("2. Waiting for the Celery worker to parse, validate and deduplicate...")
        while time.time() < deadline:
            time.sleep(3)
            current = fetch_listings(client)
            stable_polls = stable_polls + 1 if len(current) == len(listings) and len(current) > before else 0
            listings = current
            if stable_polls >= 2:
                break

    print(f"3. {len(listings)} structured listing(s) in the database:\n")
    print(f"   {'TITLE':<28} {'TYPE':<6} {'BHK':>3} {'PRICE (INR)':>14}  AREA")
    for p in listings:
        print(f"   {str(p.get('title', ''))[:28]:<28} {p.get('listing_type', ''):<6} {p.get('bhk') or 0:>3} "
              f"{p.get('price') or 0:>14,}  {p.get('area', '')}")
    print(f"\nExplore the full API at {API_URL}/docs")


if __name__ == "__main__":
    main()
