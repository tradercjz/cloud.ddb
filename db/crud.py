from typing import List
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from . import models
from schemas import UserCreate, EnvironmentCreate
from core.security import get_password_hash
from core.config import settings

# User CRUD
async def get_user_by_username(db: Session, username: str):
    result = await db.execute(select(models.User).filter(models.User.username == username))
    return result.scalars().first()

async def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(username=user.username, hashed_password=hashed_password)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

# Environment CRUD
async def get_environment(db: Session, env_id: str):
    result = await db.execute(select(models.Environment).filter(models.Environment.id == env_id))
    return result.scalars().first()

async def list_environments_by_owner(db: Session, owner_id: int):
    result = await db.execute(select(models.Environment).filter(models.Environment.owner_id == owner_id))
    return result.scalars().all()

async def create_environment(db: Session, env: EnvironmentCreate, owner_id: int):
    expires_at = datetime.utcnow() + timedelta(hours=env.lifetime_hours)
    db_env = models.Environment(
        owner_id=owner_id,
        spec_cpu=env.spec_cpu,
        spec_memory=env.spec_memory,
        expires_at=expires_at,
        region_id=settings.ALIYUN_REGION_ID,
    )
    db.add(db_env)
    await db.commit()
    await db.refresh(db_env)
    return db_env

async def update_environment_status(db: Session, env_id: str, status: str, message: str):
    env = await get_environment(db, env_id)
    if env:
        env.status = status
        env.message = message
        await db.commit()

async def update_environment_after_provisioning(db: Session, env_id: str, status: str, message: str, public_ip: str, container_group_id: str):
    env = await get_environment(db, env_id)
    if env:
        env.status = status
        env.message = message
        env.public_ip = public_ip
        env.container_group_id = container_group_id
        await db.commit()
        
async def get_expired_environments(db: Session):
    result = await db.execute(
        select(models.Environment)
        .filter(models.Environment.expires_at <= datetime.utcnow(), models.Environment.status == "RUNNING")
    )
    return result.scalars().all()

async def get_active_environments(db: Session) -> List[models.Environment]:
    """Fetches all environments that are supposed to be active on the cloud."""
    active_statuses = ["PROVISIONING", "RUNNING"]
    result = await db.execute(
        select(models.Environment)
        .filter(models.Environment.status.in_(active_statuses))
    )
    return result.scalars().all()