# apps/api/repositories/conversation_repository.py
from motor.motor_asyncio import AsyncIOMotorClient
from apps.api.schemas.conversation_schemas import ConversationAppend, MessageBlock
from datetime import datetime
from typing import Optional
import os

class ConversationRepository:
    def __init__(self):
        self.mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client["nph_core"]
        self.collection = self.db["conversations"]

    async def create_indexes(self):
        """Builds composite tracking indexes for immediate conversational history retrieval."""
        await self.collection.create_index("lead_id", unique=True)
        await self.collection.create_index("phone")

    async def append_message_to_history(self, lead_id: str, phone: str, message: ConversationAppend) -> dict:
        """Atomically pushes a new chat message into the lead's log array or initializes it if empty."""
        new_message = MessageBlock(
            role=message.role,
            content=message.content,
            timestamp=datetime.utcnow()
        ).dict()

        now = datetime.utcnow()

        # Atomic upsert engine pass
        await self.collection.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "phone": phone,
                    "channel": "whatsapp",
                    "updated_at": now
                },
                "$push": {"messages": new_message}
            },
            upsert=True
        )

        return await self.get_conversation_by_lead(lead_id)

    async def get_conversation_by_lead(self, lead_id: str) -> Optional[dict]:
        """Fetches the complete raw append-only conversation manifest for a specific lead."""
        return await self.collection.find_one({"lead_id": lead_id}, {"_id": 0})