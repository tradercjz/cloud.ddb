from fastapi import FastAPI
from contextlib import asynccontextmanager
from arq import create_pool

from core.config import settings
from api.v1.api import api_router
from worker import WorkerSettings
from db.session import engine
from db.models import Base # Import Base

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

app.include_router(api_router, prefix=settings.API_V1_STR)

# Optional: Add a root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to the DolphinDB Cloud Service"}