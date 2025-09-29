import asyncio
from datetime import datetime
from arq.connections import RedisSettings, create_pool

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

        ddb_public_ip, ddb_container_group_id = await aliyun_service.create_instance(env_schema)
        
        await crud.update_environment_after_provisioning(
            db, env_id, "PROVISIONING", "DolphinDB is ready. Creating Code-Server...",
            public_ip=ddb_public_ip,
            container_group_id=ddb_container_group_id
        )
        
        # --- 阶段 2: 创建 Code-Server 实例 ---
        print(f"[{env_id}] DolphinDB IP is {ddb_public_ip}. Now creating Code-Server instance...")
        
        # 重新从数据库加载环境信息，以防万一
        env_from_db = await crud.get_environment(db, env_id)
        env_schema = EnvironmentPublic.from_orm(env_from_db)

        # 调用新的方法创建 Code-Server，并传入 DDB 的 IP
        cs_public_ip, cs_container_group_id = await aliyun_service.create_code_server_instance(
            env_schema, ddb_public_ip
        )
        
        # --- 最终更新: 保存所有信息，并将状态设为 RUNNING ---
        await crud.update_environment_after_provisioning(
            db, env_id, "RUNNING", "Environment is ready.",
            public_ip=ddb_public_ip,
            container_group_id=ddb_container_group_id,
            code_server_public_ip=cs_public_ip,
            code_server_group_id=cs_container_group_id
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
            
        # 2. 删除 Code-Server ECI (如果存在)
        if env.code_server_group_id:
            print(f"[{env.id}] Deleting Code-Server instance: {env.code_server_group_id}")
            await aliyun_service.delete_instance(env.code_server_group_id, env.region_id)
        await crud.update_environment_status(db, env_id, "DELETED", "Successfully deleted.")
    except Exception as e:
        await crud.update_environment_status(db, env_id, "ERROR", f"Deletion failed: {e}")
    finally:
        await db.close()

async def cleanup_expired_environments_task(ctx):
    """ARQ cron job to clean up expired environments."""
    
    arq_pool = await create_pool(WorkerSettings.redis_settings)
    db = SessionLocal()
    
    try:
        print("--- CRON JOB: Running cleanup for expired environments... ---") # 添加日志
        expired_envs = await crud.get_expired_environments(db)
        
        if not expired_envs:
            print("--- CRON JOB: No expired environments found. ---")
            return

        print(f"--- CRON JOB: Found {len(expired_envs)} expired environments to clean up. ---")
        for env in expired_envs:
            await crud.update_environment_status(db, env.id, "DELETING", "Environment expired. Cleaning up.")
            

            await arq_pool.enqueue_job("delete_environment_task", env.id)
            print(f"--- CRON JOB: Enqueued deletion task for env_id: {env.id} ---")

    except Exception as e:
        # 添加错误日志
        print(f"--- CRON JOB: An ERROR occurred during cleanup: {e} ---")
    finally:
        await db.close()
        if arq_pool:
            await arq_pool.close()

async def sync_cloud_state_task(ctx):
    """
    Periodically checks our database state against the actual state in Alibaba Cloud
    and marks any missing instances as deleted.
    """
    db = SessionLocal()
    try:
        print("--- CRON JOB: Running cloud state synchronization... ---")
        active_envs = await crud.get_active_environments(db)
        if not active_envs:
            print("--- CRON JOB: No active environments to sync. ---")
            return

        # Batch instance IDs by region for efficient API calls
        ids_by_region = {}
        for env in active_envs:
            if env.region_id not in ids_by_region:
                ids_by_region[env.region_id] = []
            if env.container_group_id:
                 ids_by_region[env.region_id].append(env.container_group_id)

        all_live_instances = {}
        for region_id, group_ids in ids_by_region.items():
            live_in_region = await aliyun_service.describe_instances_batch(region_id, group_ids)
            all_live_instances.update(live_in_region)
            
        # Reconcile: Find ghosts in our DB that are not live in the cloud
        ghost_count = 0
        for env in active_envs:
            if env.container_group_id and env.container_group_id not in all_live_instances:
                ghost_count += 1
                print(f"--- CRON JOB: Found ghost environment {env.id}. Marking as DELETED. ---")
                await crud.update_environment_status(
                    db, env.id, "DELETED", "Instance was deleted from the cloud provider externally."
                )
        
        print(f"--- CRON JOB: Sync complete. Found and marked {ghost_count} ghost environments. ---")

    except Exception as e:
        print(f"--- CRON JOB: An ERROR occurred during state sync: {e} ---")
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
        ),
        cron(sync_cloud_state_task,  minute={0,5,10,15,20,25,30,35,40,45,50,55}, run_at_startup=True)
    ]
    redis_settings = RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)