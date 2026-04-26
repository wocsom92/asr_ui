from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import get_current_user, require_admin
from app.config import settings
from app.database import get_db
from app.models.transcription_model import TranscriptionModel
from app.models.user import User
from app.schemas.models import (
    ModelCatalogItem,
    ModelInstallRequest,
    TranscriptionModelOut,
)
from app.services.model_catalog import MODEL_CATALOG, get_catalog_item
from app.services.model_installer import (
    cancel_model_install,
    is_install_active,
    schedule_model_install,
)

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=list[TranscriptionModelOut])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(TranscriptionModel).order_by(
        TranscriptionModel.variant, TranscriptionModel.id
    ).where(TranscriptionModel.is_deleted.is_(False))
    if user.role != "admin":
        query = query.where(TranscriptionModel.status == "installed")
    result = await db.execute(
        query
    )
    models = result.scalars().all()
    changed = False
    for model in models:
        catalog_item = get_catalog_item(model.variant)
        if catalog_item and model.download_url != catalog_item.download_url:
            model.download_url = catalog_item.download_url
            changed = True
    if changed:
        await db.commit()
    return models


@router.get("/catalog", response_model=list[ModelCatalogItem])
async def model_catalog(_user: User = Depends(require_admin)):
    return MODEL_CATALOG


@router.post("/install", response_model=TranscriptionModelOut)
async def install(
    body: ModelInstallRequest,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    catalog_item = get_catalog_item(body.variant)
    if not catalog_item:
        raise HTTPException(status_code=404, detail="Unknown model variant")

    existing_result = await db.execute(
        select(TranscriptionModel).where(TranscriptionModel.variant == body.variant)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.is_deleted = False
        if existing.status == "installed":
            return existing
        if existing.status == "installing" and is_install_active(existing.id):
            return existing
        existing.status = "installing"
        existing.download_url = catalog_item.download_url
        existing.size_bytes = None
        existing.downloaded_bytes = 0
        existing.total_bytes = None
        existing.status_text = "Queued for download"
        existing.error_message = None
        existing.installed_at = None
        model = existing
    else:
        model = TranscriptionModel(
            provider=catalog_item.provider,
            variant=catalog_item.variant,
            display_name=catalog_item.display_name,
            language_mode=catalog_item.language_mode,
            path=str(settings.models_dir / f"ggml-{catalog_item.variant}.bin"),
            download_url=catalog_item.download_url,
            status="installing",
            downloaded_bytes=0,
            total_bytes=None,
            status_text="Queued for download",
        )
        db.add(model)

    await db.commit()
    await db.refresh(model)
    schedule_model_install(model.id)
    return model


@router.post("/{model_id}/cancel")
async def cancel_install(
    model_id: int,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionModel)
        .options(selectinload(TranscriptionModel.transcription_jobs))
        .where(TranscriptionModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status != "installing":
        return {"message": "Model is not installing"}
    await cancel_model_install(model_id)
    return {"message": "Cancelled"}


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionModel).where(TranscriptionModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status == "installing":
        await cancel_model_install(model_id)

    Path(model.path).unlink(missing_ok=True)
    Path(model.path + ".part").unlink(missing_ok=True)
    model.is_deleted = True
    model.status = "failed"
    model.size_bytes = None
    model.downloaded_bytes = 0
    model.total_bytes = None
    model.installed_at = None
    model.status_text = "Deleted"
    model.error_message = None
    await db.commit()
    return {"message": "Deleted"}
