from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# --- User Schemas ---
class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: int
    class Config:
        from_attributes = True

# --- Token Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str

# --- Environment Schemas ---
class EnvironmentBase(BaseModel):
    spec_cpu: float = Field(..., gt=0, description="vCPU cores (e.g., 2.0)")
    spec_memory: float = Field(..., gt=0, description="Memory in GiB (e.g., 4.0)")

class EnvironmentCreate(EnvironmentBase):
    lifetime_hours: int = Field(default=24, le=48, description="How long the instance will live.")

class EnvironmentPublic(EnvironmentBase):
    id: str
    owner_id: int
    status: str
    message: Optional[str] = None
    public_ip: Optional[str] = None
    port: int
    region_id: str
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True