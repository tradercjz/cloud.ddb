from typing import List, Optional
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from . import models
from schemas import UserCreate, EnvironmentCreate, FeedbackCreate 
from core.security import get_password_hash
from core.config import settings

# User CRUD
async def get_user_by_email(db: Session, email: str): 
    result = await db.execute(select(models.User).filter(models.User.email == email))
    return result.scalars().first()

async def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password, is_active=False)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def activate_user(db: Session, user: models.User): 
    user.is_active = True
    await db.commit()
    await db.refresh(user)
    return user

async def create_verification_code(db: Session, user_id: int, code: str) -> models.VerificationCode:
    expires_at = datetime.utcnow() + timedelta(minutes=settings.EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES)
    db_code = models.VerificationCode(user_id=user_id, code=code, expires_at=expires_at)
    db.add(db_code)
    await db.commit()
    await db.refresh(db_code)
    return db_code

async def get_verification_code(db: Session, email: str, code: str) -> Optional[models.VerificationCode]:
    result = await db.execute(
        select(models.VerificationCode)
        .join(models.User)
        .filter(
            models.User.email == email,
            models.VerificationCode.code == code,
            models.VerificationCode.expires_at > datetime.utcnow()
        )
    )
    return result.scalars().first()

async def delete_verification_code(db: Session, code_id: int): 
    result = await db.execute(select(models.VerificationCode).filter(models.VerificationCode.id == code_id))
    db_code = result.scalars().first()
    if db_code:
        await db.delete(db_code)
        await db.commit()
        
async def get_latest_verification_code_for_user(db: Session, user_id: int) -> Optional[models.VerificationCode]:
    """获取用户最近创建的一个验证码，用于速率限制检查。"""
    result = await db.execute(
        select(models.VerificationCode)
        .filter(models.VerificationCode.user_id == user_id)
        .order_by(models.VerificationCode.created_at.desc())
    )
    return result.scalars().first()

async def delete_all_verification_codes_for_user(db: Session, user_id: int):
    """删除一个用户所有已存在的验证码。"""
    codes_to_delete = await db.execute(
        select(models.VerificationCode).filter(models.VerificationCode.user_id == user_id)
    )
    for code in codes_to_delete.scalars().all():
        await db.delete(code)
    await db.commit()
        
        
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

async def update_environment_after_provisioning(db: Session, env_id: str, status: str, message: str, public_ip: str, container_group_id: str, code_server_public_ip: Optional[str] = None,
    code_server_group_id: Optional[str] = None):
    env = await get_environment(db, env_id)
    if env:
        env.status = status
        env.message = message
        env.public_ip = public_ip
        env.container_group_id = container_group_id
        if code_server_public_ip:
            env.code_server_public_ip = code_server_public_ip
        if code_server_group_id:
            env.code_server_group_id = code_server_group_id
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

async def create_feedback(db: Session, feedback: FeedbackCreate, owner_id: int):
    db_feedback = models.Feedback(
        turn_id=feedback.turn_id,
        owner_id=owner_id,
        feedback_type=feedback.feedback,
        prompt=feedback.prompt,
        response=feedback.response,
        conversation_history=feedback.conversation_history
    )
    db.add(db_feedback)
    await db.commit()
    await db.refresh(db_feedback)
    return db_feedback