"""Reusable FastAPI authentication and authorization dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import User
from backend.db.session import get_async_session
from backend.utils.security import decode_token

security = HTTPBearer(auto_error=False)
SessionDependency = Annotated[AsyncSession, Depends(get_async_session)]
CredentialsDependency = Annotated[
    HTTPAuthorizationCredentials | None, Depends(security)
]


async def get_current_user(
    credentials: CredentialsDependency, db: SessionDependency
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def require_editor(current_user: CurrentUser) -> User:
    if current_user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Editor access required")
    return current_user
