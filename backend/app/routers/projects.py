from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _clean_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    return value


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    value = description.strip()
    return value or None


async def _ensure_unique_project_name(
    db: AsyncSession,
    user_id: int,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    query = select(Project.id).where(
        Project.owner_user_id == user_id,
        func.lower(Project.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.where(Project.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Project name already exists")


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.owner_user_id == user.id)
        .order_by(func.lower(Project.name), Project.id)
    )
    return result.scalars().all()


@router.post("", response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = _clean_name(body.name)
    await _ensure_unique_project_name(db, user.id, name)

    project = Project(
        owner_user_id=user.id,
        name=name,
        description=_clean_description(body.description),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if "name" in body.model_fields_set:
        name = _clean_name(body.name)
        await _ensure_unique_project_name(db, user.id, name, exclude_id=project.id)
        project.name = name
    if "description" in body.model_fields_set:
        project.description = _clean_description(body.description)

    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.execute(
        update(AudioFile)
        .where(AudioFile.owner_user_id == user.id, AudioFile.project_id == project.id)
        .values(project_id=None)
    )
    await db.delete(project)
    await db.commit()
    return {"message": "Deleted"}
