from fastapi import Request
from arq.connections import ArqRedis

async def get_arq_pool(request: Request) -> ArqRedis:
    """
    A FastAPI dependency that retrieves the ARQ Redis pool
    from the application state.
    """
    return request.app.state.arq_pool