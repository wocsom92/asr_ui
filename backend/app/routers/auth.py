import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# In-memory sliding-window login throttle. Sufficient for a single-process LAN backend;
# replace with a shared store if the backend is ever horizontally scaled.
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _set_auth_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=max_age,
    )


def _enforce_login_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = settings.login_rate_limit_window_seconds
    attempts = [ts for ts in _login_attempts[key] if now - ts < window]
    if len(attempts) >= settings.login_rate_limit_attempts:
        _login_attempts[key] = attempts
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait and try again.",
        )
    attempts.append(now)
    _login_attempts[key] = attempts


def _clear_login_rate_limit(key: str) -> None:
    _login_attempts.pop(key, None)


@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    count_result = await db.execute(select(func.count()).select_from(User))
    is_first = count_result.scalar() == 0
    if not is_first:
        raise HTTPException(
            status_code=403,
            detail="Registration is closed. Ask an administrator to create an account.",
        )

    existing = await db.execute(
        select(User).where(
            (User.username == body.username) | (User.email == body.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already taken")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{body.username.lower()}"
    _enforce_login_rate_limit(rate_key)

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _clear_login_rate_limit(rate_key)
    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id, user.role)
    _set_auth_cookie(response, "access_token", access, settings.access_token_expire_minutes * 60)
    _set_auth_cookie(response, "refresh_token", refresh, settings.refresh_token_expire_days * 86400)
    return {
        "access_token": access,
        "token_type": "bearer",
        "user": UserOut.model_validate(user).model_dump(),
    }


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access = create_access_token(user.id, user.role)
    _set_auth_cookie(response, "access_token", access, settings.access_token_expire_minutes * 60)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", samesite=settings.cookie_samesite, secure=settings.cookie_secure)
    response.delete_cookie("refresh_token", samesite=settings.cookie_samesite, secure=settings.cookie_secure)
    return {"message": "Logged out"}


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not pwd_context.verify(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = pwd_context.hash(body.new_password)
    await db.commit()
    return {"message": "Password changed"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
