import asyncio
from datetime import datetime
from arq.connections import RedisSettings

from core.config import settings
from db.session import SessionLocal
from db import crud
from services.aliyun_eci import aliyun_service
from schemas import EnvironmentPublic
from arq.cron import cron

async def create_environment_task(ctx, env_id: str):
    """ARQ task to create a cloud environment."""
    db = SessionLocal()
    try:
        await crud.update_environment_status(db, env_id, "PROVISIONING", "Creating cloud resources...")
        
        env_from_db = await crud.get_environment(db, env_id)
        env_schema = EnvironmentPublic.from_orm(env_from_db)

        public_ip, container_group_id = await aliyun_service.create_instance(env_schema)
        
        await crud.update_environment_after_provisioning(
            db, env_id, "RUNNING", "Environment is ready.", public_ip, container_group_id
        )
    except Exception as e:
        await crud.update_environment_status(db, env_id, "ERROR", str(e))
    finally:
        await db.close()

async def delete_environment_task(ctx, env_id: str):
    """ARQ task to delete a cloud environment."""
    db = SessionLocal()
    try:
        env = await crud.get_environment(db, env_id)
        if env.container_group_id:
            await aliyun_service.delete_instance(env.container_group_id, env.region_id)
        await crud.update_environment_status(db, env_id, "DELETED", "Successfully deleted.")
    except Exception as e:
        await crud.update_environment_status(db, env_id, "ERROR", f"Deletion failed: {e}")
    finally:
        await db.close()

async def cleanup_expired_environments_task(ctx):
    """ARQ cron job to clean up expired environments."""
    db = SessionLocal()
    try:
        expired_envs = await crud.get_expired_environments(db)
        for env in expired_envs:
            await crud.update_environment_status(db, env.id, "DELETING", "Environment expired. Cleaning up.")
            await ctx['arq_pool'].enqueue_job("delete_environment_task", env.id)
    finally:
        await db.close()

# ARQ Worker Settings
class WorkerSettings:
    functions = [create_environment_task, delete_environment_task]
    cron_jobs = [
        # 使用 cron() 函数来创建 CronJob 对象
        cron(
            cleanup_expired_environments_task, 
            minute=0,
            run_at_startup=True
        )
    ]
    redis_settings = RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)