from fastapi import APIRouter
from api.v1.endpoints import auth, environments

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(environments.router, prefix="/environments", tags=["environments"])
