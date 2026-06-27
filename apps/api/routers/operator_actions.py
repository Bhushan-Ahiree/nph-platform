# apps/api/routers/operator_actions.py
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/operator-actions", tags=["Operations Workflow"])

class OperatorActionResponse(BaseModel):
    id: str
    action_type: str
    lead_id: str
    owner_confidence: Optional[float] = None
    source_text: Optional[str] = None
    status: str
    created_at: datetime
    
class OperatorActionUpdate(BaseModel):
    status: str

@router.get("", response_model=List[OperatorActionResponse])
async def list_actions(status: str = Query("PENDING"), action_type: Optional[str] = None):
    from shared.utils.database import db
    query = {"status": status}
    if action_type:
        query["action_type"] = action_type
        
    cursor = db.client.nph_core.operator_actions.find(query).sort("created_at", -1)
    results = await cursor.to_list(length=100)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
        
    return results

@router.patch("/{action_id}")
async def update_action(action_id: str, payload: OperatorActionUpdate):
    from shared.utils.database import db
    from bson import ObjectId
    try:
        obj_id = ObjectId(action_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid action ID")
        
    result = await db.client.nph_core.operator_actions.update_one(
        {"_id": obj_id},
        {"$set": {"status": payload.status}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action not found")
        
    action = await db.client.nph_core.operator_actions.find_one({"_id": obj_id})
    action["id"] = str(action.pop("_id"))
    return action
