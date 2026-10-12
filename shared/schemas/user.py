# shared/schemas/user.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from datetime import datetime

class UserRegister(BaseModel):
    email: EmailStr = Field(..., description="User email for login identity")
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    full_name: str = Field(..., min_length=2)
    # No role field: self-registration always creates a "client" account.
    # Staff roles (broker, admin) are granted by an administrator — see scripts/seed_users.py.

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str = Field(alias="_id")
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime

    model_config = ConfigDict(populate_by_name=True)

class Token(BaseModel):
    access_token: str
    token_type: str