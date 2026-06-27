# scripts/bulk_ingest.py
import asyncio
import httpx
import sys
import os

# Target the unified raw-chunk mass ingestion endpoint
API_URL = "http://localhost:8000/properties/raw-chunk"

async def process_bulk_file(group_name: str, filepath: str):
    """Reads the raw WhatsApp dump text and posts it to the unified ingestion endpoint."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[PACK] Read {len(content)} characters of raw dump. Ingesting to NPH pipeline...")

    payload = {
        "source_group": group_name,
        "raw_text": content
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=payload, timeout=60.0)
            if response.status_code == 202:
                print(f"[OK] Successfully ingested. Response: {response.json()}")
            else:
                print(f"[ERROR] Failed: [{response.status_code}] {response.text}")
    except Exception as e:
        print(f"[WARN] Error: {str(e)}")

if __name__ == "__main__":
    # Ensure group name and file path were passed as arguments
    if len(sys.argv) < 3:
        print("Usage: python scripts/bulk_ingest.py <group_name> <path/to/messages.txt>")
        sys.exit(1)
        
    group_name = sys.argv[1]
    target_file = sys.argv[2]
    asyncio.run(process_bulk_file(group_name, target_file))