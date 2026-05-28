from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import require_admin
from app.config import settings
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_job_chunk import TranscriptionJobChunk
from app.models.transcription_worker import TranscriptionWorker
from app.models.user import User
from app.schemas.workers import (
    WorkerClaimIn,
    WorkerClaimOut,
    WorkerFinishIn,
    WorkerHeartbeatIn,
    WorkerInstallRequestIn,
    WorkerOut,
    WorkerProgressIn,
    WorkerUninstallRequestIn,
    WorkerUpdateIn,
)
from app.services.worker_runtime import (
    add_worker_model_speed_sample,
    claim_next_work,
    list_workers,
    model_speed_stats_from_json,
    model_states_from_json,
    requested_installs_from_json,
    requested_installs_to_json,
    requested_uninstalls_from_json,
    requested_uninstalls_to_json,
    try_merge_split_job,
    upsert_worker,
    worker_is_online,
)
from app.services.summarizer import queue_summary_if_enabled

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


def _runtime_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if not started_at or not finished_at:
        return None
    if started_at.tzinfo is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    elif started_at.tzinfo is None and finished_at.tzinfo is not None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (finished_at - started_at).total_seconds()


def _require_worker_token(
    authorization: str | None = Header(default=None),
    x_asr_worker_token: str | None = Header(default=None),
) -> None:
    expected = settings.asr_worker_token
    supplied = x_asr_worker_token
    if not supplied and authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:]
    if not expected or supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid worker token")


def _worker_out(worker: TranscriptionWorker) -> WorkerOut:
    return WorkerOut(
        id=worker.id,
        name=worker.name,
        display_name=worker.display_name,
        accepted=worker.accepted,
        is_deleted=worker.is_deleted,
        status=(
            "pending"
            if not worker.accepted
            else "offline"
            if not worker_is_online(worker)
            else worker.status
        ),
        online=worker.accepted and worker_is_online(worker),
        last_heartbeat_at=worker.last_heartbeat_at,
        current_job_count=worker.current_job_count if worker_is_online(worker) else 0,
        completed_job_count=worker.completed_job_count,
        failed_job_count=worker.failed_job_count,
        cancelled_job_count=worker.cancelled_job_count,
        total_runtime_seconds=worker.total_runtime_seconds,
        total_audio_seconds=worker.total_audio_seconds,
        model_speed_stats=model_speed_stats_from_json(worker.model_speed_stats_json),
        models=model_states_from_json(worker.model_inventory_json),
        installs=model_states_from_json(worker.install_status_json),
        requested_installs=requested_installs_from_json(worker.requested_installs_json),
        requested_uninstalls=requested_uninstalls_from_json(worker.requested_uninstalls_json),
        last_error=worker.last_error,
        auto_install_models=worker.auto_install_models,
        created_at=worker.created_at,
        updated_at=worker.updated_at,
    )


@router.get("", response_model=list[WorkerOut])
async def get_workers(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return [_worker_out(worker) for worker in await list_workers(db)]


@router.patch("/{worker_id}", response_model=WorkerOut)
async def update_worker(
    worker_id: int,
    body: WorkerUpdateIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionWorker).where(TranscriptionWorker.id == worker_id)
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if "display_name" in body.model_fields_set:
        display_name = (body.display_name or "").strip()
        worker.display_name = display_name or None
    if "accepted" in body.model_fields_set and body.accepted is not None:
        worker.accepted = body.accepted
        if body.accepted and worker.status == "pending":
            worker.status = "idle" if worker_is_online(worker) else "offline"
    worker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(worker)
    return _worker_out(worker)


@router.post("/{worker_id}/install-model", response_model=WorkerOut)
async def request_worker_model_install(
    worker_id: int,
    body: WorkerInstallRequestIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.services.model_catalog import get_catalog_item

    catalog_item = get_catalog_item(body.variant)
    if not catalog_item:
        raise HTTPException(status_code=404, detail="Unknown model variant")
    result = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.id == worker_id,
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.accepted:
        raise HTTPException(status_code=409, detail="Accept the worker before installing models")
    installed = {state.variant for state in model_states_from_json(worker.model_inventory_json)}
    install_variant = catalog_item.model_variant or catalog_item.variant
    if install_variant in installed:
        return _worker_out(worker)
    requested = requested_installs_from_json(worker.requested_installs_json)
    requested.append(catalog_item.variant)
    worker.requested_installs_json = requested_installs_to_json(requested)
    worker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(worker)
    return _worker_out(worker)


@router.post("/{worker_id}/uninstall-model", response_model=WorkerOut)
async def request_worker_model_uninstall(
    worker_id: int,
    body: WorkerUninstallRequestIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.id == worker_id,
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.accepted:
        raise HTTPException(status_code=409, detail="Accept the worker before uninstalling models")
    if worker_is_online(worker) and (worker.current_job_count > 0 or worker.status == "running"):
        raise HTTPException(status_code=409, detail="Cannot uninstall a model while the worker is running work")

    installed = {state.variant for state in model_states_from_json(worker.model_inventory_json)}
    variant = body.variant.strip()
    if not variant:
        raise HTTPException(status_code=400, detail="Model variant is required")
    if variant not in installed:
        return _worker_out(worker)

    requested = requested_uninstalls_from_json(worker.requested_uninstalls_json)
    requested.append(variant)
    worker.requested_uninstalls_json = requested_uninstalls_to_json(requested)
    from app.services.model_catalog import get_catalog_item

    install_requests = []
    for item in requested_installs_from_json(worker.requested_installs_json):
        catalog_item = get_catalog_item(item)
        install_variant = catalog_item.model_variant if catalog_item and catalog_item.model_variant else item
        if item != variant and install_variant != variant:
            install_requests.append(item)
    worker.requested_installs_json = requested_installs_to_json(install_requests)
    worker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(worker)
    return _worker_out(worker)


@router.delete("/{worker_id}")
async def delete_worker(
    worker_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionWorker).where(TranscriptionWorker.id == worker_id)
    )
    worker = result.scalar_one_or_none()
    if not worker or worker.is_deleted:
        raise HTTPException(status_code=404, detail="Worker not found")
    running_job = await db.execute(
        select(TranscriptionJob.id).where(
            TranscriptionJob.worker_id == worker.id,
            TranscriptionJob.status == "running",
        )
    )
    running_chunk = await db.execute(
        select(TranscriptionJobChunk.id).where(
            TranscriptionJobChunk.worker_id == worker.id,
            TranscriptionJobChunk.status == "running",
        )
    )
    if running_job.scalar_one_or_none() is not None or running_chunk.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Cannot remove a worker while it is running work")
    worker.is_deleted = True
    worker.accepted = False
    worker.status = "offline"
    worker.current_job_count = 0
    worker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Removed"}


@router.post("/heartbeat", response_model=WorkerOut)
async def heartbeat(
    body: WorkerHeartbeatIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    worker = await upsert_worker(db, body)
    return _worker_out(worker)


@router.post("/claim", response_model=WorkerClaimOut)
async def claim(
    body: WorkerClaimIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    return await claim_next_work(db, body.name, body.models, body.auto_install_models)


async def _job_for_worker(db: AsyncSession, job_id: int, worker_name: str) -> TranscriptionJob:
    result = await db.execute(
        select(TranscriptionJob)
        .options(selectinload(TranscriptionJob.audio_file), selectinload(TranscriptionJob.model))
        .where(TranscriptionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job or job.worker_name_snapshot != worker_name:
        raise HTTPException(status_code=404, detail="Assigned job not found")
    return job


async def _chunk_for_worker(db: AsyncSession, chunk_id: int, worker_name: str) -> TranscriptionJobChunk:
    result = await db.execute(
        select(TranscriptionJobChunk)
        .options(
            selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.audio_file),
            selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.model),
        )
        .where(TranscriptionJobChunk.id == chunk_id)
    )
    chunk = result.scalar_one_or_none()
    if not chunk or chunk.worker_name_snapshot != worker_name:
        raise HTTPException(status_code=404, detail="Assigned chunk not found")
    return chunk


@router.get("/jobs/{job_id}/audio")
async def download_job_audio(
    job_id: int,
    worker_name: str,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    job = await _job_for_worker(db, job_id, worker_name)
    path = Path(job.audio_file.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is missing")
    return FileResponse(path, filename=job.audio_file.original_filename)


@router.get("/chunks/{chunk_id}/audio")
async def download_chunk_audio(
    chunk_id: int,
    worker_name: str,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    chunk = await _chunk_for_worker(db, chunk_id, worker_name)
    path = Path(chunk.parent_job.audio_file.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is missing")
    return FileResponse(path, filename=chunk.parent_job.audio_file.original_filename)


@router.post("/jobs/{job_id}/progress")
async def job_progress(
    job_id: int,
    worker_name: str,
    body: WorkerProgressIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    job = await _job_for_worker(db, job_id, worker_name)
    values = {"worker_heartbeat_at": datetime.now(timezone.utc)}
    if body.status_text is not None:
        values["status_text"] = body.status_text
    if body.partial_transcript_text is not None:
        values["partial_transcript_text"] = body.partial_transcript_text
        values["partial_transcript_json"] = body.partial_transcript_json
        values["partial_updated_at"] = datetime.now(timezone.utc)
    await db.execute(
        update(TranscriptionJob)
        .where(TranscriptionJob.id == job.id, TranscriptionJob.status == "running")
        .values(**values)
    )
    await db.commit()
    return {"cancel_requested": job.cancel_requested_at is not None}


@router.post("/chunks/{chunk_id}/progress")
async def chunk_progress(
    chunk_id: int,
    worker_name: str,
    body: WorkerProgressIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    chunk = await _chunk_for_worker(db, chunk_id, worker_name)
    if body.status_text is not None:
        chunk.status_text = body.status_text
        chunk.parent_job.status_text = f"Chunk {chunk.index + 1}: {body.status_text}"
        await db.commit()
    return {"cancel_requested": chunk.parent_job.cancel_requested_at is not None}


def _write_remote_outputs(job: TranscriptionJob, body: WorkerFinishIn) -> None:
    output_dir = settings.outputs_dir / str(job.owner_user_id) / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    if body.transcript_text is not None:
        txt_path = output_dir / "transcript.txt"
        txt_path.write_text(body.transcript_text, encoding="utf-8")
        job.output_txt_path = str(txt_path)
        job.transcript_text = body.transcript_text
    if body.output_json is not None:
        json_path = output_dir / "transcript.json"
        json_path.write_text(body.output_json, encoding="utf-8")
        job.output_json_path = str(json_path)
    if body.output_srt is not None:
        srt_path = output_dir / "transcript.srt"
        srt_path.write_text(body.output_srt, encoding="utf-8")
        job.output_srt_path = str(srt_path)
    if body.output_vtt is not None:
        vtt_path = output_dir / "transcript.vtt"
        vtt_path.write_text(body.output_vtt, encoding="utf-8")
        job.output_vtt_path = str(vtt_path)


async def _finish_worker_stats(
    db: AsyncSession,
    worker_name: str,
    status: str,
    runtime_seconds: float | None,
    audio_seconds: float | None,
    model_variant: str | None,
) -> None:
    result = await db.execute(
        select(TranscriptionWorker).where(TranscriptionWorker.name == worker_name)
    )
    worker = result.scalar_one_or_none()
    if not worker:
        return
    worker.status = "idle"
    worker.current_job_count = 0
    if status == "succeeded":
        worker.completed_job_count += 1
    elif status == "cancelled":
        worker.cancelled_job_count += 1
    else:
        worker.failed_job_count += 1
    if runtime_seconds and runtime_seconds > 0:
        worker.total_runtime_seconds += runtime_seconds
    if audio_seconds and audio_seconds > 0:
        worker.total_audio_seconds += audio_seconds
    if status == "succeeded":
        add_worker_model_speed_sample(worker, model_variant, runtime_seconds, audio_seconds)
    worker.updated_at = datetime.now(timezone.utc)


@router.post("/jobs/{job_id}/finish")
async def finish_job(
    job_id: int,
    worker_name: str,
    body: WorkerFinishIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    job = await _job_for_worker(db, job_id, worker_name)
    now = datetime.now(timezone.utc)
    if body.status == "succeeded":
        _write_remote_outputs(job, body)
        job.status = "succeeded"
        job.status_text = "Transcription finished"
        job.error_message = None
    elif body.status == "cancelled":
        job.status = "cancelled"
        job.status_text = "Cancelled"
        job.error_message = None
    else:
        job.status = "failed"
        job.status_text = "Transcription failed"
        job.error_message = body.error_message or "Worker failed"
    job.finished_at = now
    runtime = _runtime_seconds(job.started_at, job.finished_at)
    await _finish_worker_stats(
        db,
        worker_name,
        job.status,
        runtime,
        job.audio_file.duration_seconds if job.audio_file else None,
        job.model.variant if job.model else None,
    )
    await db.commit()
    if job.status == "succeeded":
        await queue_summary_if_enabled(job.id)
    return {"ok": True}


@router.post("/chunks/{chunk_id}/finish")
async def finish_chunk(
    chunk_id: int,
    worker_name: str,
    body: WorkerFinishIn,
    _: None = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    chunk = await _chunk_for_worker(db, chunk_id, worker_name)
    now = datetime.now(timezone.utc)
    if body.status == "succeeded":
        chunk.status = "succeeded"
        chunk.status_text = "Chunk finished"
        chunk.error_message = None
        chunk.transcript_text = body.transcript_text
        chunk.output_json = body.output_json
        chunk.output_srt = body.output_srt
        chunk.output_vtt = body.output_vtt
    elif body.status == "cancelled":
        chunk.status = "cancelled"
        chunk.status_text = "Cancelled"
        chunk.error_message = None
    else:
        chunk.status = "failed"
        chunk.status_text = "Chunk failed"
        chunk.error_message = body.error_message or "Worker failed"
    chunk.finished_at = now
    runtime = _runtime_seconds(chunk.started_at, chunk.finished_at)
    await _finish_worker_stats(
        db,
        worker_name,
        chunk.status,
        runtime,
        max(0.0, chunk.end_seconds - chunk.start_seconds),
        chunk.parent_job.model.variant if chunk.parent_job and chunk.parent_job.model else None,
    )
    await db.commit()
    await try_merge_split_job(db, chunk.parent_job_id)
    return {"ok": True}


@router.get("/catalog")
async def worker_catalog(
    _: None = Depends(_require_worker_token),
):
    from app.services.model_catalog import MODEL_CATALOG

    return MODEL_CATALOG
