"""
Admin 接口简易鉴权模块
基于环境变量 ADMIN_TOKEN 做 Bearer Token 校验。

用法:
    from auth import require_admin

    @app.get("/admin/xxx")
    def admin_endpoint(_user=Depends(require_admin)):
        ...

生产环境建议替换为 JWT / OAuth2 / 网关层统一鉴权。
"""
from __future__ import annotations

import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)


def _get_admin_token() -> str | None:
    token = os.getenv("ADMIN_TOKEN")
    if not token:
        return None
    token = token.strip()
    return token or None


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """校验 Bearer Token，通过则返回 token 持有者标识。"""
    admin_token = _get_admin_token()
    if admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin 鉴权未配置，当前环境已禁用管理接口",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请提供 Authorization: Bearer <token> 请求头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token 无效，拒绝访问",
        )
    return "admin"
