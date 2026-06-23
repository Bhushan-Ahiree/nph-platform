# services/whatsapp/client.py
import os
import sys
import uuid
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MetaWhatsAppClient:
    """
    Wrapper client logic for interacting with the Meta Graph Cloud API for WhatsApp.
    Handles authentication, payload formatting, and message delivery.
    """
    def __init__(self):
        self.access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.api_version = os.getenv("WHATSAPP_API_VERSION", "v20.0")
        
        # Base Graph API URL construction targeting Meta message gateway
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def send_text_message(self, to: str, text: str) -> Dict[str, Any]:
        """
        Sends a standard free-form text message to the specified recipient.
        
        Args:
            to: 10-12 digit clean phone number with country code (e.g., 919876543210).
            text: Raw message content body.
            
        Returns:
            Dict containing response metadata.
        """
        # Ensure recipient has country code. Meta requires country code prefix.
        clean_to = to.strip().replace("+", "").replace("-", "").replace(" ", "")
        if len(clean_to) == 10:
            clean_to = f"91{clean_to}"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "text",
            "text": {
                "body": text
            }
        }

        # Check if we are using a mock token outside a pytest testing environment.
        # This prevents 401 Unauthorized API failures when running locally without real Meta API keys.
        is_testing = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
        if self.access_token.startswith("mock_") and not is_testing:
            mock_id = f"mock_wamid_{uuid.uuid4().hex[:16]}"
            logger.info(f"[WhatsApp Client] [SIMULATED] Outbound message successfully processed. Meta ID: {mock_id}")
            return {
                "messaging_product": "whatsapp",
                "contacts": [{"input": clean_to, "wa_id": clean_to}],
                "messages": [{"id": mock_id}]
            }

        logger.info(f"[WhatsApp Client] Dispatching message to {clean_to}: {text[:50]}...")
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.base_url, json=payload, headers=self.headers)
                response.raise_for_status()
                result = response.json()
                logger.info(f"[WhatsApp Client] Outbound message successfully processed. Meta ID: {result.get('messages', [{}])[0].get('id')}")
                return result
        except httpx.HTTPStatusError as http_err:
            logger.error(f"[WhatsApp Client] Meta API handshake error: {http_err.response.status_code} - {http_err.response.text}")
            raise
        except Exception as e:
            logger.error(f"[WhatsApp Client] Connection failed to Meta API: {str(e)}")
            raise
