# services/ai/extraction.py
import httpx
import json
import socket

def get_docker_gateway_ip() -> str:
    """Dynamically resolves the internal bridge network gateway IP address."""
    try:
        # Resolves host.docker.internal if the DNS bridge is cooperative
        return socket.gethostbyname("host.docker.internal")
    except socket.gaierror:
        try:
            # Fallback: Look up the container's primary internal routing gateway
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            # Drop the last octet to identify the bridge network master gateway (e.g., 172.19.0.3 -> 172.19.0.1)
            parts = ip.split(".")
            parts[-1] = "1"
            return ".".join(parts)
        except Exception:
            return "172.17.0.1"

def extract_lead_parameters(text_message: str) -> dict:
    """Sends raw unstructured text to local Llama 3.2 and enforces a strict JSON schema return."""
    
    # Resolve the target host IP address at runtime
    # gateway_ip = get_docker_gateway_ip()
    # ollama_url = os.getenv("OLLAMA_URL", f"http://{gateway_ip}:11434/api/generate")
    # print(f"[AI Extraction] Connecting to Ollama endpoint: {ollama_url}")
    
    # We are forcing it to use the exact DNS name provided by Docker Desktop
    ollama_url = "http://host.docker.internal:11434/api/generate"
    print(f"[AI Extraction] Connecting strictly to Ollama endpoint: {ollama_url}")
    
    prompt = f"""
    You are an elite real estate data extraction AI for Nashik Property Hub.
    Extract the property requirements from the user's text into STRICT JSON format.
    Do not include markdown, explanations, or conversational text. ONLY output the JSON object.

    Keys required:
    - requirement_type: "rent" or "buy" (default "rent" if unsure)
    - property_type: "apartment", "villa", "plot", "commercial" (default "apartment")
    - bhk: integer (extract number of bedrooms, e.g., 2 for 2bhk. Default 0 if not mentioned)
    - preferred_areas: list of strings (e.g., ["Mahatma Nagar", "Indira Nagar", "College Road"])
    - budget_max: integer (extract maximum budget, e.g. 15000. Strip commas/currency)
    - parking: boolean (true if parking is mentioned or required, else false)

    User Text: "{text_message}"
    """
    
    payload = {
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(ollama_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            extracted_json = json.loads(result["response"])
            return extracted_json
            
    except Exception as e:
        print(f"[AI Extraction Error] Llama 3.2 Failed at {ollama_url}: {str(e)}")
        return {}