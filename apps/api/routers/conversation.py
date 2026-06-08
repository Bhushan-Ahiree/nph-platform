# apps/api/routers/conversation.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.conversation_schemas import ConversationAppend, ConversationResponse
from apps.api.repositories.conversation_repository import ConversationRepository
from apps.api.repositories.lead_repository import LeadRepository

router = APIRouter(prefix="/conversations", tags=["CRM Conversation Memory"])
conv_repo = ConversationRepository()
lead_repo = LeadRepository()

@router.post("/{lead_id}", response_model=ConversationResponse, status_code=status.HTTP_200_OK)
async def append_chat_message(lead_id: str, payload: ConversationAppend):
    """Appends a new interaction segment to a lead's timeline memory matrix."""
    lead = await lead_repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Cannot anchor conversation. Lead '{lead_id}' does not exist.")
    
    try:
        return await conv_repo.append_message_to_history(
            lead_id=lead_id,
            phone=lead["phone"],
            message=payload
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory write failure: {str(e)}")

@router.get("/{lead_id}", response_model=ConversationResponse)
async def get_chat_history(lead_id: str):
    """Retrieves the full structural message stack for downstream LLM prompt injection."""
    history = await conv_repo.get_conversation_by_lead(lead_id)
    if not history:
        raise HTTPException(status_code=404, detail=f"No conversation logs found for lead '{lead_id}'.")
    return history