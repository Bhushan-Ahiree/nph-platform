# apps/api/repositories/conversation_repository.py
from apps.api.schemas.conversation_schemas import ConversationAppend, MessageBlock
from datetime import datetime, timezone
from typing import Optional


class ConversationRepository:
    """Manages conversation thread persistence for lead interaction memory."""

    @property
    def collection(self):
        """Dynamically fetches the active collection pool via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.conversations

    async def create_indexes(self):
        """Builds composite tracking indexes for immediate conversational history retrieval."""
        await self.collection.create_index("lead_id")
        await self.collection.create_index("phone")

    async def append_message_to_history(self, lead_id: str, phone: str, message: ConversationAppend) -> dict:
        """Atomically pushes a new chat message into the lead's log array or initializes it if empty."""
        new_message = MessageBlock(
            role=message.role,
            content=message.content,
            timestamp=datetime.now(timezone.utc)
        ).model_dump()

        now = datetime.now(timezone.utc)

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