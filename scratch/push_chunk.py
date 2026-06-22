import requests

with open("d:\\nph-platform\\dump.txt", "r", encoding="utf-8") as f:
    text = f.read()

payload = {
    "source_group": "Nashik Brokers Premium",
    "raw_text": text
}

try:
    response = requests.post("http://localhost:8000/properties/raw-chunk", json=payload)
    print(f"Status: {response.status_code}")
    print(response.json())
except Exception as e:
    print(f"Failed to push chunk: {e}")
