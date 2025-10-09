# FILE: ./api/v1/endpoints/chat.py

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from schemas import InteractiveSQLRequest, UserInDB
from core.security import get_current_user
from db.session import get_db
from db import crud, models

# --- Import necessary agent components ---
import queue
import threading
import asyncio
import json
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent.interactive_sql_executor import InteractiveSQLExecutor
from agent.tool_manager import ToolManager
from agent.code_executor import CodeExecutor

# --- Import ALL tools ---
from agent.tools.enhanced_ddb_tools import (
    InspectDatabaseTool, ListTablesTool, DescribeTableTool, QueryDataTool,
    CreateSampleDataTool, OptimizeQueryTool, GetFunctionDocumentationTool, SearchKnowledgeBaseTool,
)
from agent.tools.ddb_tools import RunDolphinDBScriptTool
from agent.tools.interactive_tools import AskForHumanFeedbackTool, PlanModeResponseTool
from agent.tools.completion_tool import AttemptCompletionTool
from agent.tools.file_tools import WriteFileTool

router = APIRouter()

@router.post("/")
async def interactive_chat(
    request: InteractiveSQLRequest,
    fastapi_request: Request, # Renamed to avoid conflict
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Handles all interactive AI chat sessions.
    - If `env_id` is provided, it connects to the specified DolphinDB environment.
    - Otherwise, it runs in a database-agnostic mode with limited tools (e.g., for RAG).
    """
    env: Optional[models.Environment] = None
    
    print(f"Interactive chat requested by user {current_user.username}, env_id={request.env_id}")
    
    # --- Conditional Environment Loading ---
    if request.env_id:
        env = await crud.get_environment(db, env_id=request.env_id)
        if not env or env.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Environment not found or you don't have access.")
        if env.status != "RUNNING" or not env.public_ip:
            raise HTTPException(status_code=409, detail="Environment is not in a RUNNING state.")

    main_loop = asyncio.get_running_loop()

    # The async generator and threading logic remains the same
    async def event_generator():
        q = queue.Queue()
        request_specific_executor: Optional[CodeExecutor] = None

        def agent_thread_target(loop):
            nonlocal request_specific_executor
            try:
                # --- Conditional Tool & Agent Configuration ---
                tools = []
                print("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
                print(f"env:{env}")
                if env: # Database-aware mode
                    connection_details = {"host": env.public_ip, "port": env.port, "user": "admin", "password": "123456"}
                    request_specific_executor = CodeExecutor(**connection_details)
                    
                    # Full set of tools
                    tools = [
                        RunDolphinDBScriptTool(executor=request_specific_executor),
                        GetFunctionDocumentationTool(project_path="."),
                        InspectDatabaseTool(executor=request_specific_executor),
                        ListTablesTool(executor=request_specific_executor),
                        DescribeTableTool(executor=request_specific_executor),
                        QueryDataTool(executor=request_specific_executor),
                        # --- General tools also included ---
                        AskForHumanFeedbackTool(),
                        PlanModeResponseTool(),
                        AttemptCompletionTool(),
                        SearchKnowledgeBaseTool()
                    ]
                    
                    if env.code_server_group_id and env.region_id:
                        write_tool = WriteFileTool(
                            region_id=env.region_id,
                            container_group_id=env.code_server_group_id,
                            main_event_loop=loop
                        )
                        tools.append(write_tool)
                        print(f"Info: WriteFileTool added for env {env.id} with container_group_id {env.code_server_group_id}.")
                    else:
                        print(f"Warning: WriteFileTool not added for env {env.id} because code_server_group_id is missing.")
                else: # Database-agnostic mode
                    # Limited set of tools for RAG and general tasks
                    tools = [
                        AskForHumanFeedbackTool(),
                        PlanModeResponseTool(),
                        AttemptCompletionTool(),
                        SearchKnowledgeBaseTool()
                        # Note: No database tools are included here
                    ]

                tool_manager = ToolManager(tools)
                agent_executor = InteractiveSQLExecutor(tool_manager=tool_manager)
                
                user_input = request.conversation_history[-1]['content'] if request.conversation_history else ""
                
                task_generator = agent_executor.execute_task(
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
                q.put(None) # End signal
                # If a database executor was created, ensure it's closed
                if request_specific_executor:
                    request_specific_executor.close()

        thread = threading.Thread(target=agent_thread_target, args=(main_loop,))
        thread.start()

        # Streaming loop (this part is identical to the original implementation)
        while True:
            if await fastapi_request.is_disconnected():
                print("Client disconnected, stopping agent task.")
                break
            
            try:
                update = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if update is None:
                break
            
            if isinstance(update, Exception):
                yield f"data: {json.dumps({'type': 'error', 'content': str(update)})}\n\n"
                break
            
            if isinstance(update, BaseModel):
                json_payload = update.model_dump_json()
            elif isinstance(update, dict):
                json_payload = json.dumps(update, default=str)
            else:
                json_payload = json.dumps({"type": "unknown", "content": str(update)})
            
            yield f"data: {json_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")