from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.auth.deps import get_current_user
from app.database import get_db
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.user import User
from app.models.transcription_worker import TranscriptionWorker
from app.config import settings
from app.schemas.transcription import (
    BulkIdsRequest,
    SegmentEdit,
    SegmentsUpdate,
    TranscriptionJobListOut,
    TranscriptionJobOut,
    TranscriptionSegmentOut,
    TranscriptionStatsOut,
)

# Large TEXT columns that the list view never renders inline; the detail endpoint
# (`GET /transcriptions/{id}`) still returns them in full. Deferring them keeps the
# frequently polled list query and payload small.
_LIST_DEFERRED_FIELDS = ("transcript_text", "summary_text", "partial_transcript_json")
from app.services.event_bus import emit_job_event
from app.services.job_cancellation import signal_job_cancel
from app.services.segment_outputs import write_segment_outputs
from app.services.summarization_settings import get_summarization_settings
from app.services.summarizer import cancel_summary_job, queue_summary_job
from app.services.transcription_files import delete_transcription_outputs
from app.models.transcription_job_chunk import TranscriptionJobChunk
from app.services.worker_runtime import try_merge_split_job, worker_is_online

router = APIRouter(prefix="/api/v1/transcriptions", tags=["transcriptions"])


def _timestamp_to_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if not isinstance(value, str):
        return None

    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))
        if len(parts) == 2:
            minutes, seconds = parts
            return max(0.0, int(minutes) * 60 + float(seconds))
        return max(0.0, float(normalized))
    except ValueError:
        return None


def _segment_seconds(segment: dict[str, Any], key: str) -> float | None:
    direct = _timestamp_to_seconds(segment.get(key))
    if direct is not None:
        return direct

    timestamps = segment.get("timestamps")
    if isinstance(timestamps, dict):
        parsed = _timestamp_to_seconds(timestamps.get("from" if key == "start" else "to"))
        if parsed is not None:
            return parsed

    offsets = segment.get("offsets")
    if isinstance(offsets, dict):
        offset = offsets.get("from" if key == "start" else "to")
        if isinstance(offset, (int, float)):
            return max(0.0, float(offset) / 1000)
    return None


def _segments_from_data(data: Any) -> list[TranscriptionSegmentOut]:
    raw_segments = data.get("transcription") if isinstance(data, dict) else None
    if not isinstance(raw_segments, list):
        return []

    segments: list[TranscriptionSegmentOut] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        start = _segment_seconds(raw, "start")
        end = _segment_seconds(raw, "end")
        if not text or start is None or end is None:
            continue
        speaker = raw.get("speaker")
        speaker = str(speaker).strip() if speaker not in (None, "") else None
        segments.append(
            TranscriptionSegmentOut(start=start, end=max(start, end), text=text, speaker=speaker)
        )
    return segments


def _read_final_transcription_segments(job: TranscriptionJob) -> list[TranscriptionSegmentOut]:
    if not job.output_json_path:
        return []
    path = Path(job.output_json_path)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    return _segments_from_data(data)


def _read_partial_transcription_segments(job: TranscriptionJob) -> list[TranscriptionSegmentOut]:
    if not job.partial_transcript_json:
        return []
    try:
        data = json.loads(job.partial_transcript_json)
    except json.JSONDecodeError:
        return []
    return _segments_from_data(data)


def _read_transcription_segments(
    job: TranscriptionJob,
    source: str,
) -> list[TranscriptionSegmentOut]:
    if source == "partial":
        return _read_partial_transcription_segments(job)
    if source == "final":
        return _read_final_transcription_segments(job)
    if job.status == "succeeded":
        final = _read_final_transcription_segments(job)
        if final:
            return final
    return _read_partial_transcription_segments(job)


def _regenerate_job_outputs(job: TranscriptionJob, edits: list[SegmentEdit]) -> None:
    """Rewrite txt/json/srt/vtt outputs and transcript_text from edited segments."""
    canonical: list[dict[str, Any]] = []
    for edit in edits:
        text = edit.text.strip()
        if not text:
            continue
        start = max(0.0, float(edit.start))
        end = max(start, float(edit.end))
        item: dict[str, Any] = {
            "offsets": {"from": int(round(start * 1000)), "to": int(round(end * 1000))},
            "text": text,
        }
        speaker = (edit.speaker or "").strip()
        if speaker:
            item["speaker"] = speaker
        canonical.append(item)

    write_segment_outputs(job, canonical)


def _job_query(user_id: int):
    return (
        select(TranscriptionJob)
        .options(
            selectinload(TranscriptionJob.audio_file),
            selectinload(TranscriptionJob.audio_file).selectinload(AudioFile.project),
            selectinload(TranscriptionJob.model),
            selectinload(TranscriptionJob.chunks),
        )
        .where(TranscriptionJob.owner_user_id == user_id)
    )


def _apply_project_filter(query, project_id: str | None):
    if project_id is None:
        return query
    query = query.join(TranscriptionJob.audio_file)
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
        if len(text) == 10:  # YYYY-MM-DD
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


def _build_transcription_filters(
    *,
    project_id: str | None,
    q: str | None,
    status: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list, bool]:
    """Return (where-conditions, whether an AudioFile join is required)."""
    conditions: list = []
    join_audio = False
    if project_id is not None:
        join_audio = True
        if project_id == "none":
            conditions.append(AudioFile.project_id.is_(None))
        else:
            try:
                conditions.append(AudioFile.project_id == int(project_id))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid project filter") from exc
    if q:
        join_audio = True
        like = f"%{q.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(AudioFile.original_filename).like(like),
                func.lower(func.coalesce(AudioFile.display_name, "")).like(like),
            )
        )
    if status:
        conditions.append(TranscriptionJob.status == status)
    df = _parse_filter_date(date_from)
    if df is not None:
        conditions.append(TranscriptionJob.created_at >= df)
    dt = _parse_filter_date(date_to, end_of_day=True)
    if dt is not None:
        conditions.append(TranscriptionJob.created_at <= dt)
    return conditions, join_audio


async def _offline_worker_ids(db: AsyncSession, worker_ids: set[int]) -> set[int]:
    if not worker_ids:
        return set()
    result = await db.execute(select(TranscriptionWorker).where(TranscriptionWorker.id.in_(worker_ids)))
    workers = {worker.id: worker for worker in result.scalars().all()}
    return {
        worker_id
        for worker_id in worker_ids
        if worker_id not in workers or not worker_is_online(workers[worker_id])
    }


async def _finalize_offline_cancelled_work(
    db: AsyncSession,
    job: TranscriptionJob,
    now: datetime,
) -> bool:
    if not job.cancel_requested_at:
        return False
    if not job.split_enabled:
        if job.worker_id is None:
            return False
        offline_ids = await _offline_worker_ids(db, {job.worker_id})
        if job.worker_id not in offline_ids:
            return False
        await db.execute(
            update(TranscriptionJob)
            .where(
                TranscriptionJob.id == job.id,
                TranscriptionJob.status == "running",
            )
            .values(
                status="cancelled",
                status_text="Cancelled",
                finished_at=now,
                error_message=None,
            )
        )
        await db.commit()
        return True

    running_worker_ids = {chunk.worker_id for chunk in job.chunks if chunk.status == "running" and chunk.worker_id}
    offline_ids = await _offline_worker_ids(db, running_worker_ids)
    if not offline_ids:
        return False
    await db.execute(
        update(TranscriptionJobChunk)
        .where(
            TranscriptionJobChunk.parent_job_id == job.id,
            TranscriptionJobChunk.status == "running",
            TranscriptionJobChunk.worker_id.in_(offline_ids),
        )
        .values(
            status="cancelled",
            status_text="Cancelled",
            finished_at=now,
            error_message=None,
        )
    )
    await db.commit()
    await try_merge_split_job(db, job.id)
    return True


async def _reconcile_offline_cancelling_jobs(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(
        _job_query(user_id).where(
            TranscriptionJob.status == "running",
            TranscriptionJob.cancel_requested_at.is_not(None),
        )
    )
    changed = False
    now = datetime.now(timezone.utc)
    for job in result.scalars().all():
        changed = await _finalize_offline_cancelled_work(db, job, now) or changed
    if changed:
        await db.commit()


@router.get("", response_model=list[TranscriptionJobListOut])
async def list_transcriptions(
    response: Response,
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _reconcile_offline_cancelling_jobs(db, user.id)
    conditions, join_audio = _build_transcription_filters(
        project_id=project_id, q=q, status=status, date_from=date_from, date_to=date_to
    )

    count_query = select(func.count(func.distinct(TranscriptionJob.id))).where(
        TranscriptionJob.owner_user_id == user.id
    )
    if join_audio:
        count_query = count_query.join(TranscriptionJob.audio_file)
    for condition in conditions:
        count_query = count_query.where(condition)
    total = (await db.execute(count_query)).scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    query = _job_query(user.id)
    if join_audio:
        query = query.join(TranscriptionJob.audio_file)
    for condition in conditions:
        query = query.where(condition)
    query = query.options(*(defer(getattr(TranscriptionJob, field)) for field in _LIST_DEFERRED_FIELDS))
    query = query.order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id.desc())
    if limit is not None:
        query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/stats", response_model=TranscriptionStatsOut)
async def transcription_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TranscriptionJob).where(TranscriptionJob.owner_user_id == user.id)
    )
    jobs = result.scalars().all()

    stats = TranscriptionStatsOut(total=len(jobs))
    for job in jobs:
        if job.status == "succeeded":
            stats.finished += 1
            stats.transcript_storage_bytes += (
                (job.output_txt_size_bytes or 0)
                + (job.output_json_size_bytes or 0)
                + (job.output_srt_size_bytes or 0)
                + (job.output_vtt_size_bytes or 0)
            )
        if job.status in {"queued", "running"}:
            stats.active_transcriptions += 1
        if job.summary_status in {"queued", "running"}:
            stats.active_summaries += 1
        elif job.summary_status == "failed":
            stats.failed_summaries += 1
        elif job.summary_status == "succeeded" and job.summary_text:
            stats.completed_summaries += 1
            stats.summary_word_count += len([word for word in job.summary_text.split() if word])

    if stats.completed_summaries:
        stats.average_summary_words = round(stats.summary_word_count / stats.completed_summaries)
    return stats


@router.get("/{job_id}", response_model=TranscriptionJobOut)
async def get_transcription(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _reconcile_offline_cancelling_jobs(db, user.id)
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    return job


@router.post("/{job_id}/cancel", response_model=TranscriptionJobOut)
async def cancel_transcription(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")

    if job.status == "queued":
        now = datetime.now(timezone.utc)
        if job.split_enabled:
            await db.execute(
                update(TranscriptionJobChunk)
                .where(
                    TranscriptionJobChunk.parent_job_id == job_id,
                    TranscriptionJobChunk.status == "queued",
                )
                .values(
                    status="cancelled",
                    status_text="Cancelled",
                    finished_at=now,
                    error_message=None,
                )
            )
        res = await db.execute(
            update(TranscriptionJob)
            .where(
                TranscriptionJob.id == job_id,
                TranscriptionJob.owner_user_id == user.id,
                TranscriptionJob.status == "queued",
            )
            .values(
                status="cancelled",
                status_text="Cancelled",
                finished_at=now,
                error_message=None,
                cancel_requested_at=now,
                split_status="cancelled" if job.split_enabled else job.split_status,
            )
        )
        await db.commit()
        if res.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail="Job is no longer queued; refresh and try again.",
            )
    elif job.status == "running":
        now = datetime.now(timezone.utc)
        if job.split_enabled:
            await db.execute(
                update(TranscriptionJobChunk)
                .where(
                    TranscriptionJobChunk.parent_job_id == job_id,
                    TranscriptionJobChunk.status == "queued",
                )
                .values(
                    status="cancelled",
                    status_text="Cancelled",
                    finished_at=now,
                    error_message=None,
                )
            )
        await db.execute(
            update(TranscriptionJob)
            .where(
                TranscriptionJob.id == job_id,
                TranscriptionJob.owner_user_id == user.id,
                TranscriptionJob.status == "running",
            )
            .values(
                status_text="Cancelling…",
                split_status="running" if job.split_enabled else job.split_status,
                cancel_requested_at=now,
            )
        )
        await db.commit()
        job.cancel_requested_at = now
        await signal_job_cancel(job_id)
        await _finalize_offline_cancelled_work(db, job, now)
        if job.split_enabled:
            await try_merge_split_job(db, job_id)
    else:
        raise HTTPException(
            status_code=400,
            detail="Only queued or running jobs can be cancelled.",
        )

    refreshed = await db.execute(
        select(TranscriptionJob)
        .options(
            selectinload(TranscriptionJob.audio_file),
            selectinload(TranscriptionJob.audio_file).selectinload(AudioFile.project),
            selectinload(TranscriptionJob.model),
            selectinload(TranscriptionJob.chunks),
        )
        .where(TranscriptionJob.id == job_id, TranscriptionJob.owner_user_id == user.id)
    )
    emit_job_event(user.id, job_id)
    return refreshed.scalar_one()


@router.post("/{job_id}/summary", response_model=TranscriptionJobOut)
async def summarize_transcription(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if job.status != "succeeded" or not job.transcript_text:
        raise HTTPException(status_code=409, detail="Only finished transcriptions with text can be summarized")

    config = await get_summarization_settings(db)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Summarization is disabled")
    if not config.selected_model:
        raise HTTPException(status_code=400, detail="No summarization model selected")

    now = datetime.now(timezone.utc)
    job.summary_status = "queued"
    job.summary_error = None
    job.summary_model = config.selected_model
    job.summary_queued_at = now
    job.summary_started_at = None
    job.summary_finished_at = None
    job.summary_updated_at = now
    await db.commit()
    queue_summary_job(job.id)
    emit_job_event(user.id, job_id)

    refreshed = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    return refreshed.scalar_one()


@router.post("/{job_id}/summary/cancel", response_model=TranscriptionJobOut)
async def cancel_transcription_summary(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if job.summary_status not in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Only queued or running summaries can be cancelled.")

    now = datetime.now(timezone.utc)
    cancel_summary_job(job_id)
    job.summary_status = "cancelled"
    job.summary_error = None
    job.summary_finished_at = now
    job.summary_updated_at = now
    await db.commit()
    emit_job_event(user.id, job_id)

    refreshed = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    return refreshed.scalar_one()


@router.delete("/{job_id}")
async def delete_transcription(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if job.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Cancel the running transcription before deleting it.",
        )

    await asyncio.to_thread(delete_transcription_outputs, job)

    await db.delete(job)
    await db.commit()
    emit_job_event(user.id, job_id)
    return {"message": "Deleted"}


@router.post("/bulk-delete")
async def bulk_delete_transcriptions(
    body: BulkIdsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"deleted": 0, "skipped": []}
    result = await db.execute(
        _job_query(user.id).where(TranscriptionJob.id.in_(ids))
    )
    jobs = result.scalars().all()
    deleted = 0
    skipped: list[int] = []
    for job in jobs:
        if job.status == "running":
            skipped.append(job.id)
            continue
        await asyncio.to_thread(delete_transcription_outputs, job)
        await db.delete(job)
        deleted += 1
    await db.commit()
    emit_job_event(user.id)
    return {"deleted": deleted, "skipped": skipped}


@router.get("/{job_id}/segments", response_model=list[TranscriptionSegmentOut])
async def get_transcription_segments(
    job_id: int,
    source: str = Query("auto", pattern="^(auto|partial|final)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if source == "final" and job.status != "succeeded":
        raise HTTPException(status_code=409, detail="Transcription is not finished")
    return _read_transcription_segments(job, source)


@router.patch("/{job_id}/segments", response_model=list[TranscriptionSegmentOut])
async def update_transcription_segments(
    job_id: int,
    body: SegmentsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail="Only finished transcriptions can be edited")
    if not body.segments:
        raise HTTPException(status_code=400, detail="At least one segment is required")

    await asyncio.to_thread(_regenerate_job_outputs, job, body.segments)
    # Summary no longer matches the edited transcript; mark it stale so the user re-runs it.
    if job.summary_status == "succeeded":
        job.summary_status = "idle"
        job.summary_updated_at = datetime.now(timezone.utc)
    await db.commit()
    emit_job_event(user.id, job_id)

    refreshed = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    refreshed_job = refreshed.scalar_one()
    return _read_transcription_segments(refreshed_job, "final")


@router.get("/{job_id}/download")
async def download_transcription(
    job_id: int,
    format: str = Query("txt", pattern="^(txt|json|srt|vtt)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_job_query(user.id).where(TranscriptionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail="Transcription is not finished")

    path_value = {
        "txt": job.output_txt_path,
        "json": job.output_json_path,
        "srt": job.output_srt_path,
        "vtt": job.output_vtt_path,
    }[format]
    filename_base = Path(job.audio_file.original_filename).stem
    download_name = f"{filename_base}.transcript.{format}"

    if path_value and Path(path_value).exists():
        return FileResponse(path_value, filename=download_name)
    if format == "txt" and job.transcript_text:
        return PlainTextResponse(
            job.transcript_text,
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
        )
    raise HTTPException(status_code=404, detail=f"{format} output is not available")
