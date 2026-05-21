# apps/api/repositories/property_repository.py
from shared.utils.database import db
from typing import Optional, List, Dict, Any

class PropertyRepository:
    """Isolates all structural database execution logic for listings."""
    
    @property
    def collection(self):
        """Dynamically looks up the collection pool after database initialization."""
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.properties

    async def check_duplicate(self, title: str, city: str, locality: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({
            "title": title,
            "location.city": city,
            "location.locality": locality
        })

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.collection.insert_one(property_data)
        property_data["_id"] = str(result.inserted_id)
        return property_data

    async def find_filtered(self, query_filter: Dict[str, Any], skip: int, limit: int) -> List[Dict[str, Any]]:
        cursor = self.collection.find(query_filter).skip(skip).limit(limit)
        properties = await cursor.to_list(length=limit)
        for prop in properties:
            prop["_id"] = str(prop["_id"])
        return properties

    async def update(self, property_id: str, update_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = await self.collection.find_one_and_update(
            {"property_id": property_id},
            {"$set": update_payload},
            return_document=True
        )
        if result:
            result["_id"] = str(result["_id"])
        return result

    async def delete(self, property_id: str) -> bool:
        result = await self.collection.delete_one({"property_id": property_id})
        return result.deleted_count > 0

property_repo = PropertyRepository()