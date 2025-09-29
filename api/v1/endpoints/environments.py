
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status, Response
from typing import List, Optional
from arq.connections import ArqRedis
import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
import httpx
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from agent.code_executor import CodeExecutor
from agent.interactive_sql_executor import InteractiveSQLExecutor
from agent.tool_manager import ToolManager
from schemas import EnvironmentCreate, EnvironmentPublic, InteractiveSQLRequest, UserInDB, ChatQueryRequest, ChatQueryResponse
from db.session import get_db
from db import crud
from core.security import get_current_user
from worker import WorkerSettings
from api.dependencies import get_arq_pool_http, get_arq_pool_ws
from services.aliyun_eci import aliyun_service
import dolphindb
from typing import Dict, Any
from fastapi.responses import StreamingResponse
import json
import asyncio
from utils.json_utils import custom_json_serializer
from pydantic import BaseModel
import queue
import threading
from agent.tools.enhanced_ddb_tools import (
    InspectDatabaseTool, ListTablesTool, DescribeTableTool, QueryDataTool,
    CreateSampleDataTool, OptimizeQueryTool, GetFunctionDocumentationTool, SearchKnowledgeBaseTool,
)
from agent.tools.ddb_tools import RunDolphinDBScriptTool
from agent.tools.interactive_tools import AskForHumanFeedbackTool, PlanModeResponseTool
from agent.tools.completion_tool import AttemptCompletionTool
from fastapi import WebSocket, WebSocketDisconnect
import websockets
from starlette.responses import Response


router = APIRouter()

@router.post("/", response_model=EnvironmentPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_environment(
    env_in: EnvironmentCreate,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
    arq_pool: ArqRedis = Depends(get_arq_pool_http)
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
    arq_pool: ArqRedis = Depends(get_arq_pool_http)
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

from core.config import settings
if settings.OPENAI_API_BASE_URL:
    client = openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_API_BASE_URL,
    )
else:
    # 否则，使用默认的OpenAI官方服务
    client = openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
    )


@router.post("/{env_id}/chat", response_model=ChatQueryResponse)
async def environment_chat(
    env_id: str,
    request: ChatQueryRequest,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Handles AI-driven chat queries for a DolphinDB environment.
    """
    # 1. 授权和基础状态检查
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if env.status != "RUNNING" or not env.public_ip:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Environment is not in RUNNING state. Current status: {env.status}"
        )
        
    # 2. 构建 Prompt
    # 这是“提示工程”的核心，需要不断优化
    table_schemas_str = "\n".join([f"Table `{name}` schema: {schema}" for name, schema in request.selected_tables_schema.items()])
    
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an expert in DolphinDB scripting. Your task is to convert a user's natural language question "
                "into an executable DolphinDB script based on the provided table schemas. "
                "You must follow these rules:\n"
                "1. ONLY respond with the DolphinDB script itself, enclosed in a single markdown code block.\n"
                "2. Do not provide any explanation, preamble, or additional text.\n"
                "3. If the user's question seems dangerous or unrelated to data querying (e.g., asking to delete data or asking about your identity), "
                "respond with a single word: 'ERROR'.\n"
                "4. The script should select at most 1000 rows to avoid excessive data transfer."
            )
        },
        {
            "role": "user",
            "content": (
                f"Here are the table schemas:\n{table_schemas_str}\n\n"
                f"Here is my question: \"{request.query}\"\n\n"
                f"Provide the DolphinDB script."
            )
        }
    ]

    # 3. 调用 OpenAI API
    generated_script = None
    try:
        print("Sending prompt to OpenAI...")
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 您可以换成 gpt-4 或其他模型
            messages=prompt_messages,
            temperature=0.0 # 低温以获得更确定性的、可重复的脚本
        )
        response_text = completion.choices[0].message.content.strip()
        
        # 从markdown代码块中提取脚本
        if response_text.startswith("```") and response_text.endswith("```"):
            generated_script = response_text.split('\n', 1)[1].rsplit('\n', 1)[0].strip()
        elif response_text == 'ERROR':
             return ChatQueryResponse(response_type="error", data="The query is potentially unsafe or irrelevant.", generated_script=None)
        else:
            generated_script = response_text # 如果模型没有返回markdown，直接使用

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error calling OpenAI API: {str(e)}")

    if not generated_script:
        return ChatQueryResponse(response_type="error", data="AI failed to generate a valid script.", generated_script=None)

    # 4. 连接 DolphinDB 并执行脚本
    s = dolphindb.session()
    try:
        s.connect(env.public_ip, env.port, "admin", "123456")
        print(f"Executing generated script:\n{generated_script}")
        result = s.run(generated_script)

        # 将结果转换为前端友好的格式 (例如，如果结果是Pandas DataFrame)
        # DolphinDB Python API 返回的类型多样，需要做一些处理
        import pandas as pd
        if isinstance(result, pd.DataFrame):
            # 将DataFrame转换为字典列表，并处理NaN/NaT等JSON不兼容的值
            result_json = result.to_dict(orient='records')
        elif isinstance(result, list) or isinstance(result, dict):
             result_json = result
        else: # 标量值
            result_json = [{"result": result}]

        return ChatQueryResponse(response_type="table", data=result_json, generated_script=generated_script)

    except Exception as e:
        return ChatQueryResponse(response_type="error", data=f"Error executing DolphinDB script: {str(e)}", generated_script=generated_script)
    finally:
        s.close()

@router.post("/{env_id}/chat-stream")
async def environment_chat_stream(
    env_id: str,
    request: ChatQueryRequest,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Handles AI-driven chat queries for a DolphinDB environment using a streaming response.
    """
    # 1. 授权和基础状态检查 (与非流式版本相同)
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if env.status != "RUNNING" or not env.public_ip:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Environment is not in RUNNING state. Current status: {env.status}"
        )

    # 2. 定义一个异步生成器函数，它将逐步产生事件
    async def event_generator():
        # --- 事件 1: 告知前端流程开始 ---
        yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing query...'})}\n\n"
        await asyncio.sleep(0.1) # 短暂暂停，确保消息能及时发送

        # --- 步骤 A: 构建 Prompt 并调用 OpenAI ---
        generated_script = None
        try:
            table_schemas_str = "\n".join([f"Table `{name}` schema: {schema}" for name, schema in request.selected_tables_schema.items()])
            prompt_messages = [
                {"role": "system", "content": "You are a DolphinDB expert... (和之前一样的系统提示)"}, # 为简洁省略，请使用之前的完整提示
                {"role": "user", "content": f"Schemas:\n{table_schemas_str}\n\nQuestion: \"{request.query}\"\n\nScript:"}
            ]

            # --- 事件 2: 告知前端正在调用 AI ---
            yield f"data: {json.dumps({'type': 'status', 'content': 'Generating script with AI model...'})}\n\n"
            await asyncio.sleep(0.1)

            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.OPENAI_MODEL_NAME,
                messages=prompt_messages,
                temperature=0.0
            )
            response_text = completion.choices[0].message.content.strip()

            # 从markdown代码块中提取脚本
            if response_text.startswith("```") and response_text.endswith("```"):
                generated_script = response_text.split('\n', 1)[1].rsplit('\n', 1)[0].strip()
            elif response_text == 'ERROR':
                yield f"data: {json.dumps({'type': 'error', 'content': 'The query is potentially unsafe or irrelevant.'})}\n\n"
                return # 终止生成器
            else:
                generated_script = response_text
            
            if not generated_script:
                yield f"data: {json.dumps({'type': 'error', 'content': 'AI failed to generate a valid script.'})}\n\n"
                return

            # --- 事件 3: 将生成的脚本发送给前端 ---
            yield f"data: {json.dumps({'type': 'generated_script', 'content': generated_script})}\n\n"
            await asyncio.sleep(0.1)

        except Exception as e:
            error_message = f"Error calling AI API: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
            return # 出现错误，终止生成器

        # --- 步骤 B: 连接 DolphinDB 并执行脚本 ---
        s = dolphindb.session()
        try:
            # --- 事件 4: 告知前端正在执行脚本 ---
            yield f"data: {json.dumps({'type': 'status', 'content': 'Executing script on DolphinDB instance...'})}\n\n"
            await asyncio.sleep(0.1)

            # DolphinDB的connect和run是阻塞IO操作，使用asyncio.to_thread在单独线程中运行以避免阻塞事件循环
            await asyncio.to_thread(s.connect, env.public_ip, env.port, "admin", "123456")
            result = await asyncio.to_thread(s.run, generated_script)


            # --- 事件 5: 发送最终结果 ---
            import pandas as pd
            if isinstance(result, pd.DataFrame):
                # 将NaN, NaT等替换为None(null)，以便JSON序列化
                result_df = result.where(pd.notnull(result), None)
                result_json = result_df.to_dict(orient='records')
            elif isinstance(result, list) or isinstance(result, dict):
                result_json = result
            else:
                result_json = [{"result": result}]
            final_json_string = json.dumps(
                {'type': 'final_result', 'content': result_json},
                default=custom_json_serializer
            )
            yield f"data: {final_json_string}\n\n"

        except Exception as e:
            error_message = f"Error executing DolphinDB script: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
            return
        finally:
            s.close()
                
        # --- 事件 6: 告知流程结束 ---
        yield f"data: {json.dumps({'type': 'done', 'content': 'Process finished.'})}\n\n"


    # 3. 返回一个StreamingResponse，它会消耗上面定义的异步生成器
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/{env_id}/interactive-sql")
async def run_interactive_sql_task(
    env_id: str,
    request: InteractiveSQLRequest,
    fastapi_request: Request,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Executes a stateless interactive SQL Agent loop for a specific environment.
    Streams back all status updates from the agent's execution cycle.
    """
    # 1. 授权和环境检查
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Environment not found")
    if env.status != "RUNNING" or not env.public_ip:
        raise HTTPException(status_code=409, detail="Environment is not in a RUNNING state.")

    # 2. 获取在应用启动时创建的执行器模板
    executor_template: InteractiveSQLExecutor = fastapi_request.app.state.interactive_executor_template

    # 3. 动态创建本次请求专用的、配置了正确数据库连接的组件
    try:
        connection_details = {"host": env.public_ip, "port": env.port, "user": "admin", "password": "123456"}
        
        # 创建本次请求专用的CodeExecutor
        request_specific_executor = CodeExecutor(**connection_details)

        request_specific_tool_manager =  ToolManager([
            RunDolphinDBScriptTool(executor=request_specific_executor),
            GetFunctionDocumentationTool(project_path="."),
            InspectDatabaseTool(executor=request_specific_executor),
            ListTablesTool(executor=request_specific_executor),
            DescribeTableTool(executor=request_specific_executor),
            QueryDataTool(executor=request_specific_executor),
            CreateSampleDataTool(executor=request_specific_executor),
            OptimizeQueryTool(executor=request_specific_executor),
            AskForHumanFeedbackTool(),
            PlanModeResponseTool(),
            AttemptCompletionTool(),
            SearchKnowledgeBaseTool()
        ])
        
        # 创建本次请求专用的InteractiveSQLExecutor
        request_specific_interactive_executor = InteractiveSQLExecutor(
            tool_manager=request_specific_tool_manager
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to configure agent for environment: {e}")
        
    # 4. 定义异步生成器以处理SSE流
    async def event_generator():
        q = queue.Queue()

        def agent_thread_target():
            """在单独线程中运行同步的Agent任务生成器"""
            try:
                user_input = request.conversation_history[-1]['content'] if request.conversation_history else ""
                
                # 使用我们为本次请求特制的执行器
                task_generator = request_specific_interactive_executor.execute_task(
                    user_input=user_input,
                    conversation_history=request.conversation_history,
                    injected_context=request.injected_context
                )
                
                for update in task_generator:
                    q.put(update)
            except Exception as e:
                import traceback
                print(f"Error in agent thread: {e}\n{traceback.format_exc()}")
                q.put(e)
            finally:
                # 确保无论如何都有结束信号
                q.put(None)
                # 关闭本次请求的数据库连接
                request_specific_executor.close()

        # 启动工作线程
        thread = threading.Thread(target=agent_thread_target)
        thread.start()

        # 从队列中读取并流式发送结果
        while True:
            if await fastapi_request.is_disconnected():
                print(f"Client for env {env_id} disconnected, stopping agent task.")
                # 可以在这里添加更复杂的线程停止逻辑
                break
            
            try:
                update = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if update is None: # 结束信号
                break
            
            if isinstance(update, Exception):
                yield f"data: {json.dumps({'type': 'error', 'content': str(update)})}\n\n"
                break
            
            # 将Pydantic模型或字典转换为JSON字符串
            if isinstance(update, BaseModel):
                # 使用自定义序列化器处理特殊类型
                json_payload = update.model_dump_json()
            elif isinstance(update, dict):
                # 对于字典，我们需要手动调用json.dumps并传入default处理器
                json_payload = json.dumps(update, default=str) # 使用str作为简单的备选方案
            else:
                json_payload = json.dumps({"type": "unknown", "content": str(update)})
            
            yield f"data: {json_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")



# 创建一个可复用的 httpx 异步客户端
# allow_redirects=False 很重要，让重定向交由浏览器处理
# timeout 设置得长一些，以防 code-server 有长时间操作
client = httpx.AsyncClient(base_url="", timeout=30.0, follow_redirects=False)

@router.post("/{env_id}/codeserver/ticket", status_code=200)
async def create_codeserver_access_ticket(
    env_id: str,
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user), # 这个 endpoint 需要认证
    redis: ArqRedis = Depends(get_arq_pool_http)
):
    """
    Creates a short-lived, single-use ticket for accessing the code-server iframe.
    """
    # 验证用户是否有权访问此环境
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Environment not found")

    ticket = f"cs-ticket-{uuid.uuid4().hex}"
    # 在 Redis 中存储 ticket，并设置 60 秒过期
    # key: ticket, value: env_id (或者更复杂的json，包含用户信息)
    await redis.set(ticket, env_id, ex=60)
    
    print(f"Generated ticket {ticket} for env {env_id}")
    return {"ticket": ticket}

@router.api_route("/{env_id}/codeserver/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def reverse_proxy_code_server(
    env_id: str,
    path: str,
    request: Request,
    response: Response,
    ticket: Optional[str] = None,
    db = Depends(get_db),
    redis: ArqRedis = Depends(get_arq_pool_http)
):
    """
    Reverse proxy for the code-server instance associated with an environment.
    It forwards all requests under /codeserver/{path} to the actual code-server.
    """
    

    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.status != "RUNNING" or not env.code_server_public_ip:
        logger.error(f"[{env_id}] Environment not ready for proxy. Status: {env.status if env else 'Not Found'}, IP: {env.code_server_public_ip if env else 'N/A'}")
        raise HTTPException(status_code=409, detail="Code server is not available for this environment.")
    
    # 2. 构建目标 URL
    target_url = f"http://{env.code_server_public_ip}:{env.code_server_port}/{path}"
    
    print(f"--- REVERSE PROXY DEBUG ---")
    print(f"Request path: /{path}")
    print(f"Target URL constructed: {target_url}")
    print(f"--------------------------")

    # 3. 准备请求参数，并转发请求
    # 特别注意要排除 host header，因为它应该指向内部服务，而不是我们的代理
    headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
    
    # 确保 forwarded-for header 被正确设置
    headers['x-forwarded-for'] = request.client.host
    
    # 构建请求
    rp_req = client.build_request(
        method=request.method,
        url=target_url,
        headers=headers,
        params=request.query_params,
        content=await request.body()
    )

    # 发送请求
    try:
        rp_resp = await client.send(rp_req, stream=True)
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: cannot connect to code-server. {e}")

    # 4. 流式回传响应
    # 这对于 WebSocket 和大文件传输至关重要
    return StreamingResponse(
        rp_resp.aiter_raw(),
        status_code=rp_resp.status_code,
        headers=rp_resp.headers,
        background=BackgroundTask(rp_resp.aclose) # 确保请求关闭
    )
    

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.websocket("/{env_id}/codeserver/{path:path}")
async def websocket_proxy(
    websocket: WebSocket,
    env_id: str,
    path: str,
    ticket: Optional[str] = None,
    db = Depends(get_db),
    redis: ArqRedis = Depends(get_arq_pool_ws)
):
    """
    Manually implements a reverse proxy for WebSocket connections with detailed logging.
    """

    # --- 获取环境信息 ---
    env = await crud.get_environment(db, env_id=env_id)
    if not env or env.status != "RUNNING" or not env.code_server_public_ip:
        logger.error(f"[{env_id}] Environment not ready for WebSocket. Status: {env.status if env else 'Not Found'}, IP: {env.code_server_public_ip if env else 'N/A'}")
        await websocket.close(code=4004, reason="Code server is not available.")
        return
        
    # --- 构建目标 URL ---
    target_uri = f"ws://{env.code_server_public_ip}:{env.code_server_port}/{path}?{str(websocket.query_params)}"
    
    # --- 日志点 3: 准备接受客户端连接 ---
    logger.info(f"[{env_id}] Accepting client WebSocket connection...")
    await websocket.accept()
    logger.info(f"[{env_id}] Client WebSocket connection accepted.")

    try:
        # 准备转发的 headers
        forward_headers = dict(websocket.headers)
        target_host = f"{env.code_server_public_ip}:{env.code_server_port}"
        forward_headers['host'] = target_host

        # --- 日志点 4: 尝试连接上游服务器 ---
        logger.info(f"[{env_id}] Attempting to connect to upstream WebSocket: {target_uri}")
        
        async with websockets.connect(
            target_uri, 
            #additional_headers=forward_headers,
            open_timeout=15  # 将超时时间延长到15秒，以便观察
        ) as upstream_ws:
            
            # --- 日志点 5: 成功连接上游服务器 ---
            logger.info(f"[{env_id}] Successfully connected to upstream WebSocket. Starting bi-directional proxy.")
            
            # --- 双向转发逻辑 ---
            async def consumer(client_ws: WebSocket, upstream_ws_conn):
                try:
                    async for message in client_ws.iter_bytes():
                        await upstream_ws_conn.send(message)
                except WebSocketDisconnect:
                    logger.info(f"[{env_id}] Client WebSocket disconnected (consumer side).")

            async def producer(client_ws: WebSocket, upstream_ws_conn):
                try:
                    async for message in upstream_ws_conn:
                        await client_ws.send_bytes(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"[{env_id}] Upstream WebSocket disconnected (producer side).")

            consumer_task = asyncio.create_task(consumer(websocket, upstream_ws))
            producer_task = asyncio.create_task(producer(websocket, upstream_ws))
            
            done, pending = await asyncio.wait(
                [consumer_task, producer_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            
            for task in pending:
                task.cancel()
            
            # --- 日志点 6: 代理循环结束 ---
            logger.info(f"[{env_id}] WebSocket proxy loop finished.")

    except asyncio.TimeoutError:
        logger.error(f"[{env_id}] TIMEOUT connecting to upstream WebSocket: {target_uri}")
        await websocket.close(code=1011, reason="Upstream connection timed out.")
    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"[{env_id}] Upstream WebSocket connection failed with HTTP status {e.status_code}: {target_uri}")
        await websocket.close(code=4000 + e.status_code, reason=f"Upstream server returned status {e.status_code}")
    except WebSocketDisconnect:
        logger.info(f"[{env_id}] Client disconnected before upstream connection was fully established.")
    except Exception as e:
        logger.error(f"[{env_id}] An unexpected error occurred in WebSocket proxy: {e}", exc_info=True)
        if not websocket.client_state == websockets.protocol.State.CLOSED:
            await websocket.close(code=1011, reason="Proxy error")