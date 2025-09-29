# FILE: ./api/dependencies.py
from fastapi import Request, WebSocket
from arq.connections import ArqRedis

def get_arq_pool_from_context(context: Request | WebSocket) -> ArqRedis:
    """Internal helper to get the pool from either context type."""
    return context.app.state.arq_pool

async def get_arq_pool_http(request: Request) -> ArqRedis:
    """
    A FastAPI dependency for HTTP routes to retrieve the ARQ Redis pool.
    """
    return get_arq_pool_from_context(request)

async def get_arq_pool_ws(websocket: WebSocket) -> ArqRedis:
    """
    A FastAPI dependency for WebSocket routes to retrieve the ARQ Redis pool.
    """
    return get_arq_pool_from_context(websocket)