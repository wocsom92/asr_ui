from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import async_session_factory
from app.models.transcription_job import TranscriptionJob
from app.services.cleanup_settings import get_cleanup_settings
from app.services.transcription_files import delete_transcription_outputs

logger = logging.getLogger(__name__)
_cleanup_task: asyncio.Task | None = None
_stopping = False
_last_deleted_count = 0


async def cleanup_old_failed_cancelled_jobs() -> int:
    async with async_session_factory() as db:
        config = await get_cleanup_settings(db)
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.failed_cancelled_retention_days)
        result = await db.execute(
            select(TranscriptionJob)
            .where(
                TranscriptionJob.status.in_(["failed", "cancelled"]),
                TranscriptionJob.finished_at.is_not(None),
                TranscriptionJob.finished_at < cutoff,
            )
            .order_by(TranscriptionJob.finished_at, TranscriptionJob.id)
        )
        jobs = result.scalars().all()
        for job in jobs:
            delete_transcription_outputs(job)
            await db.delete(job)
        await db.commit()
        return len(jobs)


def get_last_cleanup_deleted_count() -> int:
    return _last_deleted_count


async def start_job_cleanup() -> None:
    global _cleanup_task, _stopping
    _stopping = False
    current_loop = asyncio.get_running_loop()
    if _cleanup_task is None or _cleanup_task.done() or _cleanup_task.get_loop() is not current_loop:
        _cleanup_task = asyncio.create_task(_cleanup_loop())


async def stop_job_cleanup() -> None:
    global _stopping
    _stopping = True
    if _cleanup_task:
        _cleanup_task.cancel()
        if _cleanup_task.get_loop() is asyncio.get_running_loop():
            try:
                await _cleanup_task
            except asyncio.CancelledError:
                pass


async def _cleanup_loop() -> None:
    global _last_deleted_count
    while not _stopping:
        try:
            _last_deleted_count = await cleanup_old_failed_cancelled_jobs()
            if _last_deleted_count:
                logger.info("Deleted %s old failed/cancelled transcription jobs", _last_deleted_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Old transcription job cleanup failed")
        await asyncio.sleep(6 * 60 * 60)
