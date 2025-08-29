
from fastapi import APIRouter, Depends, HTTPException, status, Response
from typing import List
from arq.connections import ArqRedis

from schemas import EnvironmentCreate, EnvironmentPublic, UserInDB
from db.session import get_db
from db import crud
from core.security import get_current_user
from worker import WorkerSettings
from api.dependencies import get_arq_pool
from services.aliyun_eci import aliyun_service
import dolphindb
from typing import Dict, Any

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

@router.get("/{env_id}/connection", status_code=status.HTTP_200_OK)
async def check_environment_connection(
    env_id: str,
    response: Response, # 引入Response对象以便设置状态码
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Checks the connectivity to a specific DolphinDB environment.
    """
    # 1. 从数据库获取环境信息
    env = await crud.get_environment(db, env_id=env_id)

    # 2. 授权检查：确保环境存在且属于当前用户
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")

    # 3. 状态检查：确保环境是 RUNNING 状态
    if env.status != "RUNNING" or not env.public_ip:
        # 使用 409 Conflict 表示资源存在但状态不适合操作
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail=f"Environment is not in RUNNING state. Current status: {env.status}"
        )

    # 4. 尝试连接 DolphinDB 实例
    s = dolphindb.session()

    try:
        print(f"Attempting to connect to {env.public_ip}:{env.port} for env {env.id}...")
        s.connect(env.public_ip, env.port, "admin", "123456")
        # 运行一个简单的无害命令来验证连接是否真的可用
        s.run("1+1")
        print("Connection successful.")
        return {"status": "connected", "message": "Successfully connected to the DolphinDB instance."}
    except Exception as e:
        print(f"Connection failed: {e}")
        # 使用 503 Service Unavailable 表示后端服务暂时无法访问
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to the DolphinDB instance: {str(e)}"
        )
    finally:
        s.close()

@router.get("/{env_id}/schema", response_model=Dict[str, Any])
async def get_environment_schema(
    env_id: str,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Retrieves the database schema from a specific DolphinDB environment.
    """
    # 1. 授权和基础状态检查 (与上一个接口类似)
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if env.status != "RUNNING" or not env.public_ip:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Environment is not in RUNNING state. Current status: {env.status}"
        )
    
    # 2. 连接 DolphinDB 并获取 Schema
    s = dolphindb.session()
    try:
        s.connect(env.public_ip, env.port, "admin", "123456")
        
        # 定义一个DolphinDB脚本来获取所有DFS数据库中的表及其schema
        # 注意: 这里我们只关注DFS数据库，因为它们是分布式且持久化的。
        # 您也可以修改脚本以包含内存表等。
        script = """
        def get_dfs_schema() {
            dfs_dbs = getClusterDFSDatabases()
            
            schema_info = dict(STRING,ANY)
            for(db in dfs_dbs){
                tables = getTables(database(db))
                db_tables_info = dict(STRING,ANY)
                for (table_name in tables) {
                    // 加载表对象以获取schema
                    tbl = loadTable(db, table_name)
                    col_defs = tbl.schema().colDefs
                    cols = []
                    for(col in col_defs){
                        cols.append!({
                            "name": col.name,
                            "type": col.typeString,
                            "extra": col.extra
                        })
                    }
                        
                    db_tables_info[table_name] = cols
                }
                schema_info[db] = db_tables_info
            }
            return schema_info
        }
        get_dfs_schema()
        """
        
        # 执行脚本
        schema_result = s.run(script)
        
        # 如果没有DFS数据库或表，结果可能是None或空字典，这都是正常情况
        if not schema_result:
            return {}
            
        return schema_result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve schema from the DolphinDB instance: {str(e)}"
        )
    finally:
        s.close()