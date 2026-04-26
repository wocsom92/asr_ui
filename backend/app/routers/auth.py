from fastapi import APIRouter, Depends, HTTPException, Request, Response
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.database import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id, user.role)
    response.set_cookie(
        "access_token", access, httponly=True, samesite="lax", max_age=900
    )
    response.set_cookie(
        "refresh_token", refresh, httponly=True, samesite="lax", max_age=604800
    )
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
    response.set_cookie(
        "access_token", access, httponly=True, samesite="lax", max_age=900
    )
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
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
