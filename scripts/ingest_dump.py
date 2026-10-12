# scripts/ingest_dump.py — one-shot wrapper to push a WhatsApp chat export to the raw-chunk ingestion endpoint
# Usage: python scripts/ingest_dump.py [path/to/export.txt] [group name]
import asyncio
import httpx
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

API_URL = "http://localhost:8000/properties/raw-chunk"
DEFAULT_DUMP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "samples", "sample_whatsapp_dump.txt")
DEFAULT_GROUP_NAME = "Sample Nashik Property Group"

async def ingest(dump_path: str, group_name: str):
    with open(dump_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[PACK] Read {len(content)} chars. Group: {group_name}")

    payload = {"source_group": group_name, "raw_text": content}

    async with httpx.AsyncClient() as client:
        resp = await client.post(API_URL, json=payload, timeout=60.0)
        print(f"[{'OK' if resp.status_code == 202 else 'ERROR'}] [{resp.status_code}] {resp.json()}")
        return resp.json()

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DUMP_PATH
    group = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_GROUP_NAME
    result = asyncio.run(ingest(path, group))
