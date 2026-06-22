# core/security.py
from fastapi import Depends
from shared.utils.auth_guard import get_current_user

async def get_current_user_role(current_user: dict = Depends(get_current_user)) -> str:
    """
    Extracts and maps user role from JWT token validation to commission shield categories.
    """
    db_role = str(current_user.get("role", "broker")).upper()
    if db_role == "ADMIN":
        return "ADMIN"
    elif db_role in ["BROKER", "INTERNAL", "FIELD_OPS"]:
        return "INTERNAL"
    else:
        return "PUBLIC"
