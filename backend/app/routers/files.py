from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.project import Project
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_model import TranscriptionModel
from app.models.transcription_worker import TranscriptionWorker
from app.models.user import User
from app.schemas.files import AudioFileOut, AudioFileUpdate
from app.schemas.transcription import TranscriptionCreate, TranscriptionJobOut
from app.services.audio_svc import is_supported_audio, probe_duration_seconds
from app.services.event_bus import emit_job_event
from app.services.transcriber import TranscriptionError, validate_transcription_runtime
from app.services.transcription_files import delete_transcription_outputs
from app.services.worker_runtime import create_split_chunks

router = APIRouter(prefix="/api/v1/files", tags=["files"])


class BulkFileIdsRequest(BaseModel):
    ids: list[int] = []


class BulkTranscribeRequest(BaseModel):
    ids: list[int] = []
    model_id: int
    language: str = "auto"

    model_config = {"protected_namespaces": ()}


def _iter_file_range(path: Path, start: int, end: int):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


async def _validate_project_id(
    db: AsyncSession,
    user_id: int,
    project_id: int | None,
) -> int | None:
    if project_id is None:
        return None
    result = await db.execute(
        select(Project.id).where(Project.id == project_id, Project.owner_user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_id


def _apply_project_filter(query, project_id: str | None):
    if project_id is None:
        return query
    if project_id == "none":
        return query.where(AudioFile.project_id.is_(None))
    try:
        parsed_project_id = int(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project filter") from exc
    return query.where(AudioFile.project_id == parsed_project_id)


def _parse_filter_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date filter (use YYYY-MM-DD)") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_file_filters(
    *,
    project_id: str | None,
    q: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list:
    conditions: list = []
    if project_id is not None:
        if project_id == "none":
            conditions.append(AudioFile.project_id.is_(None))
        else:
            try:
                conditions.append(AudioFile.project_id == int(project_id))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid project filter") from exc
    if q:
        like = f"%{q.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(AudioFile.original_filename).like(like),
                func.lower(func.coalesce(AudioFile.display_name, "")).like(like),
            )
        )
    df = _parse_filter_date(date_from)
    if df is not None:
        conditions.append(AudioFile.created_at >= df)
    dt = _parse_filter_date(date_to, end_of_day=True)
    if dt is not None:
        conditions.append(AudioFile.created_at <= dt)
    return conditions


@router.get("", response_model=list[AudioFileOut])
async def list_files(
    response: Response,
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = _build_file_filters(
        project_id=project_id, q=q, date_from=date_from, date_to=date_to
    )

    count_query = select(func.count()).select_from(AudioFile).where(
        AudioFile.owner_user_id == user.id
    )
    for condition in conditions:
        count_query = count_query.where(condition)
    total = (await db.execute(count_query)).scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    query = (
        select(AudioFile)
        .options(selectinload(AudioFile.project))
        .where(AudioFile.owner_user_id == user.id)
    )
    for condition in conditions:
        query = query.where(condition)
    query = query.order_by(AudioFile.created_at.desc(), AudioFile.id.desc())
    if limit is not None:
        query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=AudioFileOut)
async def upload_file(
    upload: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = upload.filename or "audio"
    if not is_supported_audio(filename):
        raise HTTPException(status_code=400, detail="Unsupported audio file type")

    suffix = Path(filename).suffix.lower()
    user_dir = settings.uploads_dir / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored_path = user_dir / f"{uuid4().hex}{suffix}"

    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    with stored_path.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                stored_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Audio file is too large")
            handle.write(chunk)

    validated_project_id = await _validate_project_id(db, user.id, project_id)
    duration = await probe_duration_seconds(stored_path)
    audio = AudioFile(
        owner_user_id=user.id,
        project_id=validated_project_id,
        original_filename=filename,
        display_name=filename,
        source="web",
        stored_path=str(stored_path),
        mime_type=upload.content_type,
        size_bytes=size,
        duration_seconds=duration,
    )
    db.add(audio)
    await db.commit()
    await db.refresh(audio)
    await db.refresh(audio, attribute_names=["project"])
    return audio


@router.patch("/{file_id}", response_model=AudioFileOut)
async def update_file(
    file_id: int,
    body: AudioFileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AudioFile).where(AudioFile.id == file_id, AudioFile.owner_user_id == user.id)
    )
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if body.display_name is not None:
        display_name = body.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=400, detail="Display name cannot be empty")
        audio.display_name = display_name
    if body.notes is not None:
        notes = body.notes.strip()
        audio.notes = notes or None
    if "project_id" in body.model_fields_set:
        audio.project_id = await _validate_project_id(db, user.id, body.project_id)

    await db.commit()
    await db.refresh(audio)
    await db.refresh(audio, attribute_names=["project"])
    return audio


@router.get("/{file_id}/audio")
async def stream_audio_file(
    file_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AudioFile).where(AudioFile.id == file_id, AudioFile.owner_user_id == user.id)
    )
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio file not found")

    path = Path(audio.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is missing")

    file_size = path.stat().st_size
    media_type = audio.mime_type or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes"}
    range_header = request.headers.get("range")

    if not range_header:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            _iter_file_range(path, 0, file_size - 1),
            media_type=media_type,
            headers=headers,
        )

    unit, _, requested_range = range_header.partition("=")
    if unit.strip().lower() != "bytes" or "-" not in requested_range:
        raise HTTPException(status_code=416, detail="Invalid range")

    start_text, _, end_text = requested_range.partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid range") from exc

    if start < 0 or start >= file_size or end < start:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable")

    end = min(end, file_size - 1)
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        }
    )
    return StreamingResponse(
        _iter_file_range(path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AudioFile)
        .options(selectinload(AudioFile.transcription_jobs))
        .where(AudioFile.id == file_id, AudioFile.owner_user_id == user.id)
    )
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if any(job.status == "running" for job in audio.transcription_jobs):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete an audio file while transcription is running",
        )

    def _remove_files() -> None:
        for job in audio.transcription_jobs:
            delete_transcription_outputs(job)
        Path(audio.stored_path).unlink(missing_ok=True)

    await asyncio.to_thread(_remove_files)
    await db.delete(audio)
    await db.commit()
    return {"message": "Deleted"}


@router.post("/bulk-delete")
async def bulk_delete_files(
    body: BulkFileIdsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"deleted": 0, "skipped": []}
    result = await db.execute(
        select(AudioFile)
        .options(selectinload(AudioFile.transcription_jobs))
        .where(AudioFile.id.in_(ids), AudioFile.owner_user_id == user.id)
    )
    files = result.scalars().all()
    deleted = 0
    skipped: list[int] = []
    for audio in files:
        if any(job.status == "running" for job in audio.transcription_jobs):
            skipped.append(audio.id)
            continue

        def _remove_files(target: AudioFile = audio) -> None:
            for job in target.transcription_jobs:
                delete_transcription_outputs(job)
            Path(target.stored_path).unlink(missing_ok=True)

        await asyncio.to_thread(_remove_files)
        await db.delete(audio)
        deleted += 1
    await db.commit()
    emit_job_event(user.id)
    return {"deleted": deleted, "skipped": skipped}


@router.post("/bulk-transcribe")
async def bulk_transcribe_files(
    body: BulkTranscribeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"created": 0}

    model_result = await db.execute(
        select(TranscriptionModel).where(
            TranscriptionModel.id == body.model_id,
            TranscriptionModel.status == "installed",
        )
    )
    model = model_result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Installed model not found")
    if model.provider != "gigaam":
        try:
            validate_transcription_runtime()
        except TranscriptionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    language = body.language
    if model.language_mode == "english":
        language = "en"
    elif model.language_mode == "russian":
        language = "ru"

    default_worker = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.name == "raspi5",
            TranscriptionWorker.accepted.is_(True),
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    preferred_worker = default_worker.scalar_one_or_none()

    files_result = await db.execute(
        select(AudioFile).where(AudioFile.id.in_(ids), AudioFile.owner_user_id == user.id)
    )
    files = files_result.scalars().all()
    created = 0
    for audio in files:
        job = TranscriptionJob(
            owner_user_id=user.id,
            audio_file_id=audio.id,
            model_id=model.id,
            language=language,
            status="queued",
            status_text="Waiting for worker",
            preferred_worker_id=preferred_worker.id if preferred_worker else None,
            preferred_worker_name_snapshot=preferred_worker.name if preferred_worker else None,
            split_enabled=False,
        )
        db.add(job)
        created += 1
    await db.commit()
    emit_job_event(user.id)
    return {"created": created}


@router.post("/{file_id}/transcriptions", response_model=TranscriptionJobOut)
async def create_transcription(
    file_id: int,
    body: TranscriptionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    audio_result = await db.execute(
        select(AudioFile)
        .options(selectinload(AudioFile.project))
        .where(AudioFile.id == file_id, AudioFile.owner_user_id == user.id)
    )
    audio = audio_result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio file not found")

    model_result = await db.execute(
        select(TranscriptionModel).where(
            TranscriptionModel.id == body.model_id,
            TranscriptionModel.status == "installed",
        )
    )
    model = model_result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Installed model not found")
    if model.provider != "gigaam":
        try:
            validate_transcription_runtime()
        except TranscriptionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model.language_mode == "english" and body.language not in {"auto", "en"}:
        raise HTTPException(status_code=400, detail="English-only models only support English")
    if model.language_mode == "russian" and body.language not in {"auto", "ru"}:
        raise HTTPException(status_code=400, detail="Russian model profiles only support Russian")

    preferred_worker = None
    split_workers: list[TranscriptionWorker] = []
    if body.split_enabled and body.split_worker_ids:
        worker_result = await db.execute(
            select(TranscriptionWorker).where(
                TranscriptionWorker.id.in_(body.split_worker_ids),
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        found_by_id = {worker.id: worker for worker in worker_result.scalars().all()}
        missing_ids = [worker_id for worker_id in body.split_worker_ids if worker_id not in found_by_id]
        if missing_ids:
            raise HTTPException(status_code=404, detail="One or more selected split workers were not found")
        split_workers = [found_by_id[worker_id] for worker_id in body.split_worker_ids]
        if len(split_workers) < 2:
            raise HTTPException(status_code=400, detail="Choose at least two workers for split transcription")
    elif body.preferred_worker_id is not None:
        worker_result = await db.execute(
            select(TranscriptionWorker).where(
                TranscriptionWorker.id == body.preferred_worker_id,
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        preferred_worker = worker_result.scalar_one_or_none()
        if not preferred_worker:
            raise HTTPException(status_code=404, detail="Selected worker not found")
    else:
        worker_result = await db.execute(
            select(TranscriptionWorker).where(
                TranscriptionWorker.name == "raspi5",
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        preferred_worker = worker_result.scalar_one_or_none()

    language = body.language
    if model.language_mode == "english" and body.language == "auto":
        language = "en"
    if model.language_mode == "russian" and body.language == "auto":
        language = "ru"
    job = TranscriptionJob(
        owner_user_id=user.id,
        audio_file_id=audio.id,
        model_id=model.id,
        language=language,
        status="queued",
        status_text="Waiting for worker",
        preferred_worker_id=None if split_workers else (preferred_worker.id if preferred_worker else None),
        preferred_worker_name_snapshot=(
            f"Splitter: {', '.join(worker.display_name or worker.name for worker in split_workers)}"
            if split_workers
            else preferred_worker.name if preferred_worker else None
        ),
        split_worker_ids_json=json.dumps([worker.id for worker in split_workers]) if split_workers else None,
        split_enabled=body.split_enabled,
        split_status="queued" if body.split_enabled else None,
    )
    db.add(job)
    await db.flush()
    if body.split_enabled:
        job.audio_file = audio
        job.model = model
        try:
            await create_split_chunks(db, job)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()

    result = await db.execute(
        select(TranscriptionJob)
        .options(
            selectinload(TranscriptionJob.audio_file),
            selectinload(TranscriptionJob.audio_file).selectinload(AudioFile.project),
            selectinload(TranscriptionJob.model),
            selectinload(TranscriptionJob.chunks),
        )
        .where(TranscriptionJob.id == job.id)
    )
    created = result.scalar_one()
    emit_job_event(user.id, created.id)
    return created
