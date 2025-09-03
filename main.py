from fastapi import FastAPI
from contextlib import asynccontextmanager
from arq import create_pool

from core.config import settings
from api.v1.api import api_router
from worker import WorkerSettings
from db.session import engine
from db.models import Base # Import Base
from fastapi.middleware.cors import CORSMiddleware

from agent.interactive_sql_executor import InteractiveSQLExecutor
from agent.tool_manager import ToolManager
from agent.tools.ddb_tools import RunDolphinDBScriptTool
from agent.tools.enhanced_ddb_tools import (
    InspectDatabaseTool, ListTablesTool, DescribeTableTool, QueryDataTool,
    CreateSampleDataTool, OptimizeQueryTool, GetFunctionDocumentationTool, SearchKnowledgeBaseTool,
)
from agent.tools.interactive_tools import AskForHumanFeedbackTool, PlanModeResponseTool
from agent.tools.completion_tool import AttemptCompletionTool
from agent.code_executor import CodeExecutor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    global arq_pool
    # Connect to Redis for ARQ
    app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("INFO:     Initializing Stateless Agent Components...")
    try:
        # 创建一个临时的 RAG 实例 (即使不用，某些工具构造函数也需要)
        # 我们可以创建一个模拟/空的RAG对象来避免初始化真实RAG的开销

        
        # 创建一个 "模板" CodeExecutor，它将在每次请求时被重新配置
        template_executor = CodeExecutor()

        # 初始化工具管理器
        # 注意：这里的executor是临时的，会在请求中被替换
        tool_manager = ToolManager([
            RunDolphinDBScriptTool(executor=template_executor),
            GetFunctionDocumentationTool(project_path="."),
            InspectDatabaseTool(executor=template_executor),
            ListTablesTool(executor=template_executor),
            DescribeTableTool(executor=template_executor),
            QueryDataTool(executor=template_executor),
            CreateSampleDataTool(executor=template_executor),
            OptimizeQueryTool(executor=template_executor),
            AskForHumanFeedbackTool(),
            PlanModeResponseTool(),
            AttemptCompletionTool(),
            SearchKnowledgeBaseTool()
        ])
        
        # 初始化交互式SQL执行器
        interactive_executor = InteractiveSQLExecutor(tool_manager)

        # 将这些组件存入 app.state
        app.state.interactive_executor_template = interactive_executor
        
        print("INFO:     Stateless Agent Components initialized.")
    except Exception as e:
        print(f"FATAL:    Failed to initialize Stateless Agent Components: {e}")
        import traceback
        traceback.print_exc()

    yield # The application runs here

    # --- Shutdown ---
    if getattr(app.state, "arq_pool", None):
        await app.state.arq_pool.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

origins = [
   "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 允许访问的源
    allow_credentials=True,  # 支持 cookie
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头
)
app.include_router(api_router, prefix=settings.API_V1_STR)

# Optional: Add a root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to the DolphinDB Cloud Service"}