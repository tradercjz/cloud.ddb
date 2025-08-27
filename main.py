from fastapi import FastAPI
from contextlib import asynccontextmanager
from arq import create_pool

from core.config import settings
from api.v1.api import api_router
from worker import WorkerSettings
from db.session import engine
from db.models import Base # Import Base
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    global arq_pool
    # Connect to Redis for ARQ
    app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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