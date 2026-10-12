# scripts/ingest_dump.py — one-shot wrapper to push a WhatsApp chat export to the raw-chunk ingestion endpoint
# Usage: python scripts/ingest_dump.py [path/to/export.txt] [group name]
import asyncio
import httpx
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

API_BASE = os.getenv("DEMO_API_URL", "http://localhost:8000")
DEFAULT_DUMP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "samples", "sample_whatsapp_dump.txt")
DEFAULT_GROUP_NAME = "Sample Nashik Property Group"

async def ingest(dump_path: str, group_name: str):
    with open(dump_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[PACK] Read {len(content)} chars. Group: {group_name}")

    payload = {"source_group": group_name, "raw_text": content}

    async with httpx.AsyncClient() as client:
        # raw-chunk is staff-only: log in with the seeded admin account
        login = await client.post(f"{API_BASE}/auth/login", data={
            "username": os.getenv("ADMIN_EMAIL", ""), "password": os.getenv("ADMIN_PASSWORD", "")})
        if login.status_code != 200:
            sys.exit(f"Login failed ({login.status_code}). Set ADMIN_EMAIL / ADMIN_PASSWORD and run scripts/seed_users.py.")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        resp = await client.post(f"{API_BASE}/properties/raw-chunk", json=payload, headers=headers, timeout=60.0)
        print(f"[{'OK' if resp.status_code == 202 else 'ERROR'}] [{resp.status_code}] {resp.json()}")
        return resp.json()

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DUMP_PATH
    group = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_GROUP_NAME
    result = asyncio.run(ingest(path, group))
