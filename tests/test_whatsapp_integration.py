# tests/test_whatsapp_integration.py
import pytest
from unittest.mock import patch, MagicMock
from services.whatsapp.client import MetaWhatsAppClient
from apps.worker.tasks.whatsapp_tasks import send_whatsapp_message

@pytest.fixture(autouse=True)
def patch_whatsapp_db(mock_db):
    """
    Automatically redirects database calls inside the whatsapp_tasks module
    to utilize the mocked in-memory database client.
    """
    with patch("apps.worker.tasks.whatsapp_tasks.db", mock_db.client.nph_core):
        yield

def test_whatsapp_client_send_text_success():
    """
    Verifies that MetaWhatsAppClient formats payloads correctly and returns success response on 200 OK.
    """
    client = MetaWhatsAppClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
        "messages": [{"id": "wamid.HBgLOTg3NjU0MzIxMCEF..."}]
    }
    
    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        result = client.send_text_message("919876543210", "Hello World")
        
        assert result["messages"][0]["id"] == "wamid.HBgLOTg3NjU0MzIxMCEF..."
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["to"] == "919876543210"
        assert kwargs["json"]["text"]["body"] == "Hello World"

def test_whatsapp_client_send_text_normalization():
    """
    Verifies that 10-digit Indian numbers are formatted with country code 91.
    """
    client = MetaWhatsAppClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "123"}]}
    
    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        client.send_text_message("9876543210", "Hello World")
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["to"] == "919876543210"

@pytest.mark.asyncio
async def test_send_whatsapp_message_task_success(mock_db):
    """
    Verifies Celery task inserts pending log, calls client, and updates log status to sent on success.
    """
    # Clean mock collections
    logs_col = mock_db.client.nph_core.whatsapp_message_logs
    logs_col._docs = []
    
    mock_client_instance = MagicMock()
    mock_client_instance.send_text_message.return_value = {
        "messages": [{"id": "wamid.123"}]
    }
    
    with patch("apps.worker.tasks.whatsapp_tasks.MetaWhatsAppClient", return_value=mock_client_instance):
        result = send_whatsapp_message("919876543210", "Test Celery Delivery")
        
        assert result["status"] == "sent"
        assert result["meta_id"] == "wamid.123"
        
        # Verify db log entry exists and is updated
        assert len(logs_col._docs) == 1
        log = logs_col._docs[0]
        assert log["recipient_phone"] == "919876543210"
        assert log["content"] == "Test Celery Delivery"
        assert log["status"] == "sent"
        assert log["meta_message_id"] == "wamid.123"

@pytest.mark.asyncio
async def test_send_whatsapp_message_task_failure(mock_db):
    """
    Verifies Celery task marks status as failed when Meta API call fails.
    """
    logs_col = mock_db.client.nph_core.whatsapp_message_logs
    logs_col._docs = []
    
    mock_client_instance = MagicMock()
    mock_client_instance.send_text_message.side_effect = RuntimeError("Meta API is offline")
    
    with patch("apps.worker.tasks.whatsapp_tasks.MetaWhatsAppClient", return_value=mock_client_instance):
        with pytest.raises(RuntimeError):
            send_whatsapp_message("919876543210", "Failed Delivery attempt")
            
        assert len(logs_col._docs) == 1
        log = logs_col._docs[0]
        assert log["status"] == "failed"
        assert "Meta API is offline" in log["error"]
