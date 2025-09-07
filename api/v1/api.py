from fastapi import APIRouter
from api.v1.endpoints import auth, chat, environments, feedback

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(environments.router, prefix="/environments", tags=["environments"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"]) 