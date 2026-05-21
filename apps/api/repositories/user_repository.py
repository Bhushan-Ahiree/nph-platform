# apps/api/repositories/user_repository.py
from shared.utils.database import db
from bson import ObjectId
from typing import Optional, Dict, Any

class UserRepository:
    """Isolates all physical database operations for the Users collection."""
    
    @property
    def collection(self):
        """Dynamically looks up the collection pool after database initialization."""
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.users

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email})

    async def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not ObjectId.is_valid(user_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(user_id)})

    async def create(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.collection.insert_one(user_data)
        user_data["_id"] = str(result.inserted_id)
        return user_data

user_repo = UserRepository()