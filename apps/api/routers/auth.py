# apps/api/routes/auth.py
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from shared.schemas.user import UserRegister, UserResponse, Token
from shared.utils.security import hash_password, verify_password, create_access_token
from apps.api.repositories.user_repository import user_repo  # REPO CONVERSION
from datetime import datetime, timezone

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserRegister):
    user_dict = user_in.model_dump()
    
    # Using clean repository calls instead of raw mongo chains
    existing_user = await user_repo.get_by_email(user_dict["email"])
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address is already registered."
        )
        
    raw_password = user_dict.pop("password")
    user_dict["hashed_password"] = hash_password(raw_password)
    user_dict["created_at"] = datetime.now(timezone.utc)
    
    created_user = await user_repo.create(user_dict)
    return created_user

@router.post("/login", response_model=Token)
async def login_user(credentials: OAuth2PasswordRequestForm = Depends()):
    user = await user_repo.get_by_email(credentials.username)
    if not user or not verify_password(credentials.password, user["hashed_password"]):
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