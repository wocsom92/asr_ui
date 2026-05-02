from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.config import default_worker_name, settings
from app.database import async_session_factory
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_job_chunk import TranscriptionJobChunk
from app.models.transcription_model import TranscriptionModel
from app.models.transcription_worker import TranscriptionWorker
from app.services.job_cancellation import dispose_job_cancel_event, prepare_job_cancel_event
from app.services.model_catalog import get_catalog_item, model_storage_path
from app.services.model_installer import install_model
from app.services.telegram_bot import notify_transcription_finished
from app.services.transcriber import TranscriptionCancelled, transcribe_audio
from app.schemas.workers import WorkerHeartbeatIn, WorkerModelState
from app.services.worker_runtime import (
    add_worker_model_speed_sample,
    claim_next_work,
    try_merge_split_job,
    upsert_worker,
)

logger = logging.getLogger(__name__)
_worker_task: asyncio.Task | None = None
_stopping = False


def _runtime_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if not started_at or not finished_at:
        return None
    if started_at.tzinfo is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    elif started_at.tzinfo is None and finished_at.tzinfo is not None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (finished_at - started_at).total_seconds()


async def start_transcription_queue() -> None:
    global _worker_task, _stopping
    if not settings.asr_worker_enabled:
        return
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
        local_worker_name = default_worker_name()
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
            .where(
                TranscriptionJob.status == "running",
                (
                    (TranscriptionJob.worker_name_snapshot == local_worker_name)
                    | TranscriptionJob.worker_name_snapshot.is_(None)
                ),
            )
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
        failed_chunks = await db.execute(
            update(TranscriptionJobChunk)
            .where(
                TranscriptionJobChunk.status == "running",
                (
                    (TranscriptionJobChunk.worker_name_snapshot == local_worker_name)
                    | TranscriptionJobChunk.worker_name_snapshot.is_(None)
                ),
            )
            .values(
                status="failed",
                status_text="Transcription interrupted",
                finished_at=now,
                error_message="The worker stopped while this chunk was running.",
            )
        )
        await db.commit()

        split_cancel_result = await db.execute(
            select(TranscriptionJob)
            .options(selectinload(TranscriptionJob.chunks))
            .where(
                TranscriptionJob.split_enabled.is_(True),
                TranscriptionJob.cancel_requested_at.is_not(None),
                TranscriptionJob.status.in_(["queued", "running"]),
            )
        )
        split_cancelled = 0
        for job in split_cancel_result.scalars().all():
            await try_merge_split_job(db, job.id)
            split_cancelled += 1

    recovered = (
        cancelled.rowcount
        + failed.rowcount
        + failed_chunks.rowcount
        + split_cancelled
    )
    if recovered:
        logger.warning(
            "Reconciled %s interrupted transcription job(s) on startup "
            "(cancelled=%s failed=%s split_cancelled=%s)",
            recovered,
            cancelled.rowcount,
            failed.rowcount,
            split_cancelled,
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
    worker_name = default_worker_name()
    async with async_session_factory() as db:
        models = await _local_model_states(db)
        await upsert_worker(
            db,
            WorkerHeartbeatIn(
                name=worker_name,
                status="idle",
                current_job_count=0,
                models=models,
                installs=[],
                auto_install_models=settings.asr_worker_auto_install_models,
            ),
            accepted_default=True,
        )
        claim = await claim_next_work(
            db,
            worker_name,
            models,
            settings.asr_worker_auto_install_models,
        )
    if claim.kind == "job" and claim.job_id:
        await _process_claimed_job(claim.job_id, worker_name)
        return True
    if claim.kind == "chunk" and claim.chunk_id:
        await _process_claimed_chunk(claim.chunk_id, worker_name)
        return True
    if claim.kind == "install" and claim.model_variant:
        await _process_claimed_install(claim.model_variant, worker_name)
        return True
    if claim.kind == "uninstall" and claim.model_variant:
        await _process_claimed_uninstall(claim.model_variant, worker_name)
        return True
    return False


async def _local_model_states(db) -> list[WorkerModelState]:
    result = await db.execute(select(TranscriptionModel).where(TranscriptionModel.status == "installed"))
    states: list[WorkerModelState] = []
    for model in result.scalars().all():
        states.append(
            WorkerModelState(
                variant=model.variant.removesuffix(".ru"),
                status="installed",
                path=model.path,
                downloaded_bytes=model.size_bytes or 0,
                total_bytes=model.size_bytes,
            )
        )
    return states


async def _record_worker_finished(
    worker_name: str,
    status: str,
    runtime_seconds: float | None,
    audio_seconds: float | None,
    model_variant: str | None,
) -> None:
    async with async_session_factory() as db:
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
        await db.commit()


async def _process_claimed_install(variant: str, worker_name: str) -> None:
    catalog_item = get_catalog_item(variant)
    if not catalog_item:
        await _record_local_worker_error(worker_name, f"Unknown model variant: {variant}")
        return

    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionModel).where(TranscriptionModel.variant == variant))
        model = result.scalar_one_or_none()
        if model is None:
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
                status_text="Queued for local worker install",
            )
            db.add(model)
            await db.commit()
            await db.refresh(model)
        else:
            model.provider = catalog_item.provider
            model.display_name = catalog_item.display_name
            model.language_mode = catalog_item.language_mode
            model.path = str(model_storage_path(catalog_item.model_variant or catalog_item.variant))
            model.download_url = catalog_item.download_url
            model.status = "installing"
            model.downloaded_bytes = 0
            model.total_bytes = None
            model.size_bytes = None
            model.status_text = "Queued for local worker install"
            model.error_message = None
            model.is_deleted = False
            await db.commit()
            model_id = model.id
            await db.refresh(model)
            model.id = model_id
        model_id = model.id

    try:
        await install_model(model_id)
    except Exception as exc:
        await _record_local_worker_error(worker_name, str(exc))
        return

    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionWorker).where(TranscriptionWorker.name == worker_name))
        worker = result.scalar_one_or_none()
        if worker:
            worker.status = "idle"
            worker.current_job_count = 0
            worker.last_error = None
            worker.updated_at = datetime.now(timezone.utc)
            await db.commit()


async def _process_claimed_uninstall(variant: str, worker_name: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionModel).where(TranscriptionModel.variant == variant))
        model = result.scalar_one_or_none()
        if model:
            path = Path(model.path)
            if path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            model.status = "failed"
            model.status_text = "Deleted"
            model.size_bytes = None
            model.downloaded_bytes = 0
            model.total_bytes = None
            model.is_deleted = True
            model.error_message = None

        worker_result = await db.execute(select(TranscriptionWorker).where(TranscriptionWorker.name == worker_name))
        worker = worker_result.scalar_one_or_none()
        if worker:
            worker.status = "idle"
            worker.current_job_count = 0
            worker.updated_at = datetime.now(timezone.utc)
        await db.commit()


async def _record_local_worker_error(worker_name: str, error: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionWorker).where(TranscriptionWorker.name == worker_name))
        worker = result.scalar_one_or_none()
        if worker:
            worker.status = "idle"
            worker.current_job_count = 0
            worker.last_error = error
            worker.updated_at = datetime.now(timezone.utc)
            await db.commit()


async def _process_claimed_job(job_id: int, worker_name: str) -> None:
    async with async_session_factory() as db:
        cancel_event = await prepare_job_cancel_event(job_id)
        try:
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
            last_partial_update = 0.0

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
                        .values(
                            status_text=status_text,
                            worker_heartbeat_at=datetime.now(timezone.utc),
                        )
                    )
                    await progress_db.commit()

                last_progress_text = status_text
                last_progress_update = now_monotonic

            async def partial_callback(segments: list[dict], force: bool) -> None:
                nonlocal last_partial_update
                now_monotonic = asyncio.get_running_loop().time()
                if not force and now_monotonic - last_partial_update < 2.0:
                    return

                transcript_text = "\n".join(
                    str(segment.get("text", "")).strip()
                    for segment in segments
                    if str(segment.get("text", "")).strip()
                )
                payload = json.dumps(
                    {"transcription": segments},
                    ensure_ascii=False,
                    indent="\t",
                )
                async with async_session_factory() as partial_db:
                    await partial_db.execute(
                        update(TranscriptionJob)
                        .where(
                            TranscriptionJob.id == job_id,
                            TranscriptionJob.status == "running",
                        )
                        .values(
                            partial_transcript_text=transcript_text,
                            partial_transcript_json=payload,
                            partial_updated_at=datetime.now(timezone.utc),
                            worker_heartbeat_at=datetime.now(timezone.utc),
                        )
                    )
                    await partial_db.commit()

                last_partial_update = now_monotonic

            try:
                outputs = await transcribe_audio(
                    job,
                    job.audio_file,
                    job.model,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                    partial_callback=partial_callback,
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
                await notify_transcription_finished(job)
                runtime = _runtime_seconds(job.started_at, job.finished_at)
                await _record_worker_finished(
                    worker_name,
                    job.status,
                    runtime,
                    job.audio_file.duration_seconds if job.audio_file else None,
                    job.model.variant if job.model else None,
                )
        finally:
            await dispose_job_cancel_event(job_id)


async def _process_claimed_chunk(chunk_id: int, worker_name: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(TranscriptionJobChunk)
            .options(
                selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.audio_file),
                selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.model),
            )
            .where(TranscriptionJobChunk.id == chunk_id)
        )
        chunk = result.scalar_one()
        job = chunk.parent_job
        cancel_event = await prepare_job_cancel_event(job.id)

        async def progress_callback(status_text: str) -> None:
            async with async_session_factory() as progress_db:
                await progress_db.execute(
                    update(TranscriptionJobChunk)
                    .where(
                        TranscriptionJobChunk.id == chunk_id,
                        TranscriptionJobChunk.status == "running",
                    )
                    .values(status_text=status_text)
                )
                await progress_db.execute(
                    update(TranscriptionJob)
                    .where(TranscriptionJob.id == job.id)
                    .values(
                        status_text=f"Chunk {chunk.index + 1}: {status_text}",
                        worker_heartbeat_at=datetime.now(timezone.utc),
                    )
                )
                await progress_db.commit()

        try:
            output_dir = settings.outputs_dir / str(job.owner_user_id) / str(job.id) / f"chunk-{chunk.index}"
            outputs = await transcribe_audio(
                job,
                job.audio_file,
                job.model,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
                output_dir=output_dir,
                clip_start_seconds=chunk.start_seconds,
                clip_end_seconds=chunk.end_seconds,
            )
            chunk.transcript_text = Path(outputs["output_txt_path"]).read_text(encoding="utf-8", errors="replace") if outputs.get("output_txt_path") else outputs.get("transcript_text")
            chunk.output_json = Path(outputs["output_json_path"]).read_text(encoding="utf-8", errors="replace") if outputs.get("output_json_path") else None
            chunk.output_srt = Path(outputs["output_srt_path"]).read_text(encoding="utf-8", errors="replace") if outputs.get("output_srt_path") else None
            chunk.output_vtt = Path(outputs["output_vtt_path"]).read_text(encoding="utf-8", errors="replace") if outputs.get("output_vtt_path") else None
            chunk.status = "succeeded"
            chunk.status_text = "Chunk finished"
            chunk.error_message = None
        except TranscriptionCancelled:
            chunk.status = "cancelled"
            chunk.status_text = "Cancelled"
            chunk.error_message = None
        except Exception as exc:
            chunk.status = "failed"
            chunk.status_text = "Chunk failed"
            chunk.error_message = str(exc)
        finally:
            chunk.finished_at = datetime.now(timezone.utc)
            await db.commit()
            runtime = _runtime_seconds(chunk.started_at, chunk.finished_at)
            await _record_worker_finished(
                worker_name,
                chunk.status,
                runtime,
                max(0.0, chunk.end_seconds - chunk.start_seconds),
                job.model.variant if job.model else None,
            )
            await try_merge_split_job(db, job.id)
            await dispose_job_cancel_event(job.id)
