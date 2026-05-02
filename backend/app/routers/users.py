from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserStatsOut, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _validate_role(role: str) -> None:
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Role must be admin or user")


@router.get("/", response_model=list[UserOut])
async def list_users(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.username))
    return result.scalars().all()


@router.get("/stats", response_model=list[UserStatsOut])
async def list_user_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    audio_counts_subq = (
        select(
            AudioFile.owner_user_id.label("user_id"),
            func.count(AudioFile.id).label("audio_file_count"),
            func.sum(case((func.coalesce(AudioFile.source, "web") == "web", 1), else_=0)).label("web_audio_count"),
            func.sum(case((func.coalesce(AudioFile.source, "web") == "telegram", 1), else_=0)).label("telegram_audio_count"),
        )
        .group_by(AudioFile.owner_user_id)
        .subquery()
    )
    job_counts_subq = (
        select(
            TranscriptionJob.owner_user_id.label("user_id"),
            func.count(TranscriptionJob.id).label("transcription_count"),
            func.sum(case((TranscriptionJob.status == "running", 1), else_=0)).label("running_job_count"),
        )
        .group_by(TranscriptionJob.owner_user_id)
        .subquery()
    )
    result = await db.execute(
        select(
            User.id,
            User.username,
            User.email,
            User.role,
            func.coalesce(audio_counts_subq.c.audio_file_count, 0),
            func.coalesce(job_counts_subq.c.transcription_count, 0),
            func.coalesce(job_counts_subq.c.running_job_count, 0),
            func.coalesce(audio_counts_subq.c.web_audio_count, 0),
            func.coalesce(audio_counts_subq.c.telegram_audio_count, 0),
        )
        .outerjoin(audio_counts_subq, audio_counts_subq.c.user_id == User.id)
        .outerjoin(job_counts_subq, job_counts_subq.c.user_id == User.id)
        .order_by(User.username)
    )
    return [
        UserStatsOut(
            user_id=row[0],
            username=row[1],
            email=row[2],
            role=row[3],
            audio_file_count=row[4],
            transcription_count=row[5],
            running_job_count=row[6],
            web_audio_count=row[7],
            telegram_audio_count=row[8],
        )
        for row in result.all()
    ]


@router.post("/", response_model=UserOut)
async def create_user(
    body: UserCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_role(body.role)
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
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        _validate_role(body.role)
        user.role = body.role
    if body.password is not None:
        user.password_hash = pwd_context.hash(body.password)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return {"message": "Deleted"}
