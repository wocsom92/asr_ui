from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session_factory
from app.models.transcription_job import TranscriptionJob
from app.services.job_cancellation import dispose_job_cancel_event, prepare_job_cancel_event
from app.services.transcriber import TranscriptionCancelled, transcribe_audio

logger = logging.getLogger(__name__)
_worker_task: asyncio.Task | None = None
_stopping = False


async def start_transcription_queue() -> None:
    global _worker_task, _stopping
    _stopping = False
    await reconcile_interrupted_jobs()
    current_loop = asyncio.get_running_loop()
    if (
        _worker_task is None
        or _worker_task.done()
        or _worker_task.get_loop() is not current_loop
    ):
        _worker_task = asyncio.create_task(_worker_loop())


async def stop_transcription_queue() -> None:
    global _stopping
    _stopping = True
    if _worker_task:
        _worker_task.cancel()
        if _worker_task.get_loop() is not asyncio.get_running_loop():
            return
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


async def reconcile_interrupted_jobs() -> None:
    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)
        cancelled = await db.execute(
            update(TranscriptionJob)
            .where(
                TranscriptionJob.status == "running",
                TranscriptionJob.status_text == "Cancelling…",
            )
            .values(
                status="cancelled",
                status_text="Cancelled",
                finished_at=now,
                error_message=None,
            )
        )
        failed = await db.execute(
            update(TranscriptionJob)
            .where(TranscriptionJob.status == "running")
            .values(
                status="failed",
                status_text="Transcription interrupted",
                finished_at=now,
                error_message=(
                    "The backend stopped while this transcription was running. "
                    "Retry the job."
                ),
            )
        )
        await db.commit()

    recovered = cancelled.rowcount + failed.rowcount
    if recovered:
        logger.warning(
            "Reconciled %s interrupted transcription job(s) on startup "
            "(cancelled=%s failed=%s)",
            recovered,
            cancelled.rowcount,
            failed.rowcount,
        )


async def _worker_loop() -> None:
    while not _stopping:
        try:
            processed = await _process_next_job()
            if not processed:
                await asyncio.sleep(settings.transcription_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Transcription worker iteration failed")
            await asyncio.sleep(settings.transcription_poll_seconds)


async def _process_next_job() -> bool:
    async with async_session_factory() as db:
        result = await db.execute(
            select(TranscriptionJob.id)
            .where(TranscriptionJob.status == "queued")
            .order_by(TranscriptionJob.created_at, TranscriptionJob.id)
            .limit(1)
        )
        job_id = result.scalar_one_or_none()
        if job_id is None:
            return False

        cancel_event = await prepare_job_cancel_event(job_id)
        try:
            now = datetime.now(timezone.utc)
            upd = await db.execute(
                update(TranscriptionJob)
                .where(
                    TranscriptionJob.id == job_id,
                    TranscriptionJob.status == "queued",
                )
                .values(
                    status="running",
                    status_text="Preparing audio",
                    started_at=now,
                )
            )
            if upd.rowcount != 1:
                await db.rollback()
                return False
            await db.commit()

            result = await db.execute(
                select(TranscriptionJob)
                .options(
                    selectinload(TranscriptionJob.audio_file),
                    selectinload(TranscriptionJob.model),
                )
                .where(TranscriptionJob.id == job_id)
            )
            job = result.scalar_one()
            last_progress_text = "Preparing audio"
            last_progress_update = asyncio.get_running_loop().time()

            async def progress_callback(status_text: str) -> None:
                nonlocal last_progress_text, last_progress_update
                now_monotonic = asyncio.get_running_loop().time()
                force = status_text in {"Preparing audio", "Loading model"} or status_text.endswith("100%")
                if status_text == last_progress_text:
                    return
                if not force and now_monotonic - last_progress_update < 1.5:
                    return

                async with async_session_factory() as progress_db:
                    await progress_db.execute(
                        update(TranscriptionJob)
                        .where(
                            TranscriptionJob.id == job_id,
                            TranscriptionJob.status == "running",
                        )
                        .values(status_text=status_text)
                    )
                    await progress_db.commit()

                last_progress_text = status_text
                last_progress_update = now_monotonic

            try:
                outputs = await transcribe_audio(
                    job,
                    job.audio_file,
                    job.model,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
                for key, value in outputs.items():
                    setattr(job, key, value)
                job.status = "succeeded"
                job.status_text = "Transcription finished"
                job.error_message = None
            except TranscriptionCancelled:
                job.status = "cancelled"
                job.status_text = "Cancelled"
                job.error_message = None
            except FileNotFoundError as exc:
                job.status = "failed"
                job.status_text = "Transcription failed"
                missing = exc.filename or str(exc)
                job.error_message = (
                    f"Required executable or file is missing: {missing}. "
                    "If this is whisper-cli, use Docker or set WHISPER_CPP_BIN to a valid local whisper-cli path."
                )
            except Exception as exc:
                job.status = "failed"
                job.status_text = "Transcription failed"
                job.error_message = str(exc)
            finally:
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
        finally:
            await dispose_job_cancel_event(job_id)

    return True
