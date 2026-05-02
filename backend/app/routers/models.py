from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import shutil
from statistics import median

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import get_current_user, require_admin
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_job_chunk import TranscriptionJobChunk
from app.models.transcription_model import TranscriptionModel
from app.models.user import User
from app.schemas.models import (
    ModelCatalogItem,
    ModelInstallRequest,
    TranscriptionModelStatsOut,
    TranscriptionModelOut,
)
from app.services.model_catalog import MODEL_CATALOG, get_catalog_item, model_storage_path
from app.services.model_installer import (
    cancel_model_install,
    is_install_active,
    schedule_model_install,
)

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@dataclass
class _ModelStatsAccumulator:
    worker_id: int | None = None
    worker_name: str | None = None
    completed_job_count: int = 0
    total_audio_seconds: float = 0.0
    total_runtime_seconds: float = 0.0
    per_hour_values: list[float] = field(default_factory=list)
    last_completed_at: datetime | None = None


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


@router.get("/stats", response_model=list[TranscriptionModelStatsOut])
async def model_stats(
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    normal_result = await db.execute(
        select(
            TranscriptionModel.id,
            TranscriptionJob.worker_id,
            TranscriptionJob.worker_name_snapshot,
            TranscriptionJob.started_at,
            TranscriptionJob.finished_at,
            AudioFile.duration_seconds,
        )
        .join(TranscriptionJob, TranscriptionJob.model_id == TranscriptionModel.id)
        .join(AudioFile, AudioFile.id == TranscriptionJob.audio_file_id)
        .where(
            TranscriptionModel.is_deleted.is_(False),
            TranscriptionJob.status == "succeeded",
            TranscriptionJob.split_enabled.is_not(True),
            TranscriptionJob.started_at.is_not(None),
            TranscriptionJob.finished_at.is_not(None),
            AudioFile.duration_seconds.is_not(None),
            AudioFile.duration_seconds > 0,
        )
        .order_by(TranscriptionModel.id, TranscriptionJob.finished_at)
    )

    stats_by_model_worker: dict[tuple[int, int | None, str | None], _ModelStatsAccumulator] = {}

    def add_sample(
        *,
        model_id: int,
        worker_id: int | None,
        worker_name: str | None,
        started_at: datetime,
        finished_at: datetime,
        audio_seconds: float,
    ) -> None:
        runtime_seconds = (finished_at - started_at).total_seconds()
        if runtime_seconds <= 0 or audio_seconds <= 0:
            return

        key = (model_id, worker_id, worker_name)
        stats = stats_by_model_worker.setdefault(
            key,
            _ModelStatsAccumulator(worker_id=worker_id, worker_name=worker_name),
        )
        stats.completed_job_count += 1
        stats.total_audio_seconds += audio_seconds
        stats.total_runtime_seconds += runtime_seconds
        stats.per_hour_values.append((runtime_seconds / audio_seconds) * 3600)
        if stats.last_completed_at is None or finished_at > stats.last_completed_at:
            stats.last_completed_at = finished_at

    for model_id, worker_id, worker_name, started_at, finished_at, audio_seconds in normal_result.all():
        add_sample(
            model_id=model_id,
            worker_id=worker_id,
            worker_name=worker_name,
            started_at=started_at,
            finished_at=finished_at,
            audio_seconds=audio_seconds,
        )

    chunk_result = await db.execute(
        select(
            TranscriptionModel.id,
            TranscriptionJobChunk.worker_id,
            TranscriptionJobChunk.worker_name_snapshot,
            TranscriptionJobChunk.started_at,
            TranscriptionJobChunk.finished_at,
            TranscriptionJobChunk.start_seconds,
            TranscriptionJobChunk.end_seconds,
        )
        .join(TranscriptionJob, TranscriptionJob.id == TranscriptionJobChunk.parent_job_id)
        .join(TranscriptionModel, TranscriptionModel.id == TranscriptionJob.model_id)
        .where(
            TranscriptionModel.is_deleted.is_(False),
            TranscriptionJobChunk.status == "succeeded",
            TranscriptionJobChunk.started_at.is_not(None),
            TranscriptionJobChunk.finished_at.is_not(None),
            TranscriptionJobChunk.end_seconds > TranscriptionJobChunk.start_seconds,
        )
        .order_by(TranscriptionModel.id, TranscriptionJobChunk.finished_at)
    )
    for model_id, worker_id, worker_name, started_at, finished_at, start_seconds, end_seconds in chunk_result.all():
        add_sample(
            model_id=model_id,
            worker_id=worker_id,
            worker_name=worker_name,
            started_at=started_at,
            finished_at=finished_at,
            audio_seconds=max(0.0, float(end_seconds) - float(start_seconds)),
        )

    return [
        TranscriptionModelStatsOut(
            model_id=model_id,
            worker_id=stats.worker_id,
            worker_name=stats.worker_name,
            completed_job_count=stats.completed_job_count,
            total_audio_seconds=stats.total_audio_seconds,
            total_runtime_seconds=stats.total_runtime_seconds,
            runtime_per_audio_hour_seconds=(
                stats.total_runtime_seconds / stats.total_audio_seconds * 3600
            ),
            median_runtime_per_audio_hour_seconds=median(stats.per_hour_values),
            last_completed_at=stats.last_completed_at,
        )
        for (model_id, _worker_id, worker_name), stats in sorted(
            stats_by_model_worker.items(),
            key=lambda item: (item[0][0], (item[0][2] or "").lower(), item[0][1] or 0),
        )
    ]


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
        existing.provider = catalog_item.provider
        existing.display_name = catalog_item.display_name
        existing.language_mode = catalog_item.language_mode
        existing.path = str(model_storage_path(catalog_item.model_variant or catalog_item.variant))
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
            path=str(model_storage_path(catalog_item.model_variant or catalog_item.variant)),
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

    model_path = Path(model.path)
    if model_path.is_dir():
        shutil.rmtree(model_path, ignore_errors=True)
    else:
        model_path.unlink(missing_ok=True)
    part_path = Path(model.path + ".part")
    if part_path.is_dir():
        shutil.rmtree(part_path, ignore_errors=True)
    else:
        part_path.unlink(missing_ok=True)
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
