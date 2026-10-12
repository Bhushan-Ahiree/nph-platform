# shared/utils/auth_guard.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from shared.utils.database import db
from shared.utils.security import JWT_SECRET, JWT_ALGORITHM

# 1. Point FastAPI to our login endpoint for token collection
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Intercepts requests, decodes the JWT token, and validates the user profile."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 2. Decode and cryptographically verify the token signature
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("email")
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        
        if email is None or user_id is None:
            raise credentials_exception
            
    except InvalidTokenError:
        raise credentials_exception
        
    # 3. Double check MongoDB to ensure the user profile still physically exists
    user = await db.client.nph_core.users.find_one({"email": email})
    if user is None:
        raise credentials_exception
        
    # Return a clean dictionary containing verified profile meta-data
    return {
        "id": str(user["_id"]),
        "email": email,
        "role": role,
        "full_name": user.get("full_name")
    }

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