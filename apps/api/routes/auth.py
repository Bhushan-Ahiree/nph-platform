# apps/api/routes/auth.py

from fastapi import APIRouter, HTTPException, status, Depends  # ADDED: Depends
from fastapi.security import OAuth2PasswordRequestForm       # ADDED: Form handler
from shared.schemas.user import UserRegister, UserLogin, UserResponse, Token
from shared.utils.security import hash_password, verify_password, create_access_token
from shared.utils.database import db
from datetime import datetime, timezone

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserRegister):
    """Creates a new user profile with securely hashed credentials."""
    
    user_dict = user_in.model_dump()
    
    # 1. Enforce unique identity check across the ecosystem
    existing_user = await db.client.nph_core.users.find_one({"email": user_dict["email"]})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address is already registered."
        )
        
    # 2. Extract raw password, hash it, and overwrite the plain text
    raw_password = user_dict.pop("password")
    user_dict["hashed_password"] = hash_password(raw_password)
    
    # 3. Add system metadata
    user_dict["created_at"] = datetime.now(timezone.utc)
    
    # 4. Write record to the users collection inside MongoDB
    result = await db.client.nph_core.users.insert_one(user_dict)
    
    # 5. Fetch the saved document and format for public serialization safely
    created_user = await db.client.nph_core.users.find_one({"_id": result.inserted_id})
    created_user["_id"] = str(created_user["_id"])
    
    return created_user

@router.post("/login", response_model=Token)
async def login_user(credentials: OAuth2PasswordRequestForm = Depends()):
    """Verifies user credentials from form or Swagger and issues a secure JWT token."""
    
    # NOTE: OAuth2PasswordRequestForm uses .username instead of .email natively
    user = await db.client.nph_core.users.find_one({"email": credentials.username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password credentials provided."
        )
        
    if not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password credentials provided."
        )
        
    token_data = {
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user["role"]
    }
    access_token = create_access_token(data=token_data)
    
    return {"access_token": access_token, "token_type": "bearer"}