# FILE: ./api/middleware.py

import time
from typing import Callable
from datetime import datetime, timedelta, timezone
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware 
from starlette.responses import Response
from jose import jwt, JWTError, ExpiredSignatureError
from core.config import settings
from core.security import create_access_token

class TokenAutoRefreshMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        
        # 1. 首先，正常处理请求并获取响应
        response = await call_next(request)
        
        # 2. 从请求头中获取 token
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        if not token:
            return response # 如果没有 token，直接返回原始响应

        try:
            # 3. 解码 token 来获取其 payload，特别是 'exp'
            # 我们只关心它是否有效和它的过期时间，不关心用户是谁
            payload = jwt.decode(
                token, 
                settings.SECRET_KEY, 
                algorithms=["HS256"],
                options={"verify_signature": True, "verify_exp": True} # 确保验证签名和过期
            )
            
            exp_timestamp = payload.get("exp")
            if not exp_timestamp:
                return response

            # 4. 检查是否需要刷新 token (核心逻辑)
            # 将 Unix 时间戳转换为 datetime 对象
            expire_time = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            current_time = datetime.now(timezone.utc)
            
            total_duration_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
            refresh_threshold_minutes = total_duration_minutes / 2
            
            time_remaining = expire_time - current_time
            
            # 如果剩余时间小于总时长的一半，就刷新
            if time_remaining < timedelta(minutes=refresh_threshold_minutes):
                # 提取 'sub' claim (即用户的 email) 用于生成新 token
                user_email = payload.get("sub")
                if user_email:
                    # 创建一个新的 token，其过期时间也是配置中的时长
                    new_token = create_access_token(data={"sub": user_email})
                    
                    # 5. 将新 token 放入响应头中
                    # 使用 'Access-Control-Expose-Headers' 允许前端JS访问这个自定义头
                    response.headers["X-New-Token"] = new_token
                    if "Access-Control-Expose-Headers" in response.headers:
                        response.headers["Access-Control-Expose-Headers"] += ", X-New-Token"
                    else:
                        response.headers["Access-Control-Expose-Headers"] = "X-New-Token"

        except ExpiredSignatureError:
            # Token 已经过期，此时我们什么都不做。
            # FastAPI 的依赖项 (get_current_user) 会处理这个错误并返回 401。
            pass
        except JWTError:
            # Token 无效 (签名错误等)，同样什么都不做，让依赖项去处理。
            pass
        
        return response