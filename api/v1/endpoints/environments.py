
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from arq.connections import ArqRedis

from schemas import EnvironmentCreate, EnvironmentPublic, UserInDB
from db.session import get_db
from db import crud
from core.security import get_current_user
from worker import WorkerSettings
from api.dependencies import get_arq_pool
from services.aliyun_eci import aliyun_service

router = APIRouter()

@router.post("/", response_model=EnvironmentPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_environment(
    env_in: EnvironmentCreate,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
    arq_pool: ArqRedis = Depends(get_arq_pool)
):
    """
    Create a new DolphinDB environment.
    This starts an asynchronous background task.
    """
    new_env = await crud.create_environment(db, env=env_in, owner_id=current_user.id)
    await arq_pool.enqueue_job("create_environment_task", new_env.id)
    return new_env

@router.get("/", response_model=List[EnvironmentPublic])
async def list_environments(
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    List all environments for the current user.
    """
    return await crud.list_environments_by_owner(db, owner_id=current_user.id)

@router.get("/{env_id}", response_model=EnvironmentPublic)
async def get_environment_status(
    env_id: str,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """

    Get the status and details of a specific environment.
    """
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Environment not found")
    
    if env.status == "RUNNING" and env.container_group_id:
        live_instances = await aliyun_service.describe_instances_batch(
            env.region_id, [env.container_group_id]
        )
        if env.container_group_id not in live_instances:
            print(f"Reactive check failed for {env_id}. Updating status.")
            await crud.update_environment_status(
                db, env.id, "DELETED", "Instance was not found on the cloud provider (verified on-demand)."
            )
            # Re-fetch the updated record to return to the user
            env = await crud.get_environment(db, env_id=env_id)

    return env

@router.delete("/{env_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_environment(
    env_id: str,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
    arq_pool: ArqRedis = Depends(get_arq_pool)
):
    """
    Schedule an environment for deletion.
    """
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Environment not found")
    
    await crud.update_environment_status(db, env_id, "DELETING", "Scheduled for deletion.")
    await arq_pool.enqueue_job("delete_environment_task", env_id)
    return {"message": "Environment deletion scheduled."}