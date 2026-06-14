# scripts/bulk_ingest.py
import asyncio
import httpx
import sys
import os

# The local API endpoint we built earlier
API_URL = "http://localhost:8000/inventory/ingest"

async def ingest_single_property(client: httpx.AsyncClient, raw_text: str, index: int):
    """Fires a single scraped message to the AI extraction API."""
    try:
        response = await client.post(API_URL, json={"raw_message": raw_text}, timeout=120.0)
        if response.status_code == 200:
            print(f"✅ [{index}] Successfully ingested.")
        else:
            print(f"❌ [{index}] Failed: {response.text}")
    except Exception as e:
        print(f"⚠️ [{index}] Error: {str(e)}")

async def process_bulk_file(filepath: str):
    """Reads a text file, splits by blank lines, and processes concurrently."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Split the massive text dump by double newlines (typical between WhatsApp messages)
    raw_messages = [msg.strip() for msg in content.split("\n\n") if len(msg.strip()) > 20]
    
    print(f"📦 Found {len(raw_messages)} potential properties in the file. Starting AI extraction...")

    # We use AsyncClient to fire requests in parallel, limited to 5 at a time 
    # so we don't melt your local Llama/Ollama instance.
    semaphore = asyncio.Semaphore(1) 

    async def sem_task(client, msg, i):
        async with semaphore:
            await ingest_single_property(client, msg, i)

    async with httpx.AsyncClient() as client:
        tasks = [sem_task(client, msg, i+1) for i, msg in enumerate(raw_messages)]
        await asyncio.gather(*tasks)

    print("\n🎉 Bulk Ingestion Complete. Check MongoDB!")

if __name__ == "__main__":
    # Ensure a file was passed as an argument
    if len(sys.argv) < 2:
        print("Usage: python scripts/bulk_ingest.py path/to/messages.txt")
        sys.exit(1)
        
    target_file = sys.argv[1]
    asyncio.run(process_bulk_file(target_file))