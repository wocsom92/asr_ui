from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.transcription_job import TranscriptionJob
from app.schemas.summarization_settings import (
    OllamaModelOut,
    SummarizationPullStatus,
    SummarizationSettings,
)
from app.services.event_bus import emit_summary_event
from app.services.summarization_settings import get_summarization_settings

logger = logging.getLogger(__name__)

_active_summary_tasks: dict[int, asyncio.Task] = {}
_summary_run_lock = asyncio.Lock()
_pull_task: asyncio.Task | None = None
_pull_status = SummarizationPullStatus()

_CHUNK_CHAR_LIMIT = 5000
_OLLAMA_CONTEXT_TOKENS = 4096
_OLLAMA_NUM_PREDICT = 512
_OLLAMA_TIMEOUT_SECONDS = 900


class SummarizationError(RuntimeError):
    pass


def pull_status() -> SummarizationPullStatus:
    return _pull_status


async def ollama_health(config: SummarizationSettings) -> tuple[bool, str | None]:
    try:
        async with httpx.AsyncClient(base_url=config.ollama_base_url, timeout=5.0) as client:
            response = await client.get("/api/version")
            response.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


async def ollama_models(config: SummarizationSettings) -> list[OllamaModelOut]:
    try:
        async with httpx.AsyncClient(base_url=config.ollama_base_url, timeout=10.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        return []
    models: list[OllamaModelOut] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        models.append(
            OllamaModelOut(
                name=name,
                size=raw.get("size") if isinstance(raw.get("size"), int) else None,
                modified_at=str(raw.get("modified_at")) if raw.get("modified_at") else None,
            )
        )
    return sorted(models, key=lambda item: item.name.lower())


async def start_model_pull(config: SummarizationSettings, model: str) -> None:
    global _pull_task, _pull_status
    if _pull_task and not _pull_task.done():
        raise SummarizationError(f"Model pull already running: {_pull_status.model}")
    _pull_status = SummarizationPullStatus(
        status="running",
        model=model,
        message="Starting pull",
        error=None,
        updated_at=datetime.now(timezone.utc),
    )
    _pull_task = asyncio.create_task(_pull_model(config, model))


async def _pull_model(config: SummarizationSettings, model: str) -> None:
    global _pull_status
    try:
        async with httpx.AsyncClient(base_url=config.ollama_base_url, timeout=None) as client:
            async with client.stream("POST", "/api/pull", json={"name": model, "stream": True}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = str(payload.get("status") or "").strip()
                    if message:
                        _pull_status = SummarizationPullStatus(
                            status="running",
                            model=model,
                            message=message,
                            error=None,
                            updated_at=datetime.now(timezone.utc),
                        )
        _pull_status = SummarizationPullStatus(
            status="succeeded",
            model=model,
            message="Model ready",
            error=None,
            updated_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.exception("Ollama model pull failed")
        _pull_status = SummarizationPullStatus(
            status="failed",
            model=model,
            message=None,
            error=str(exc),
            updated_at=datetime.now(timezone.utc),
        )


async def queue_summary_if_enabled(job_id: int) -> None:
    async with async_session_factory() as db:
        config = await get_summarization_settings(db)
        result = await db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        if job.source == "telegram":
            # Telegram audio is only summarized when the admin has auto-summarize enabled.
            requested = config.auto_summarize and job.telegram_summary_requested
        else:
            requested = config.auto_summarize
        if not requested:
            return
        if not config.enabled or not config.selected_model:
            if job.telegram_summary_requested:
                now = datetime.now(timezone.utc)
                job.summary_status = "failed"
                job.summary_error = (
                    "Summarization is disabled"
                    if not config.enabled
                    else "No summarization model selected"
                )
                job.summary_model = config.selected_model or job.summary_model
                job.summary_finished_at = now
                job.summary_updated_at = now
                await db.commit()
                emit_summary_event(job.owner_user_id, job_id)
                await _notify_telegram_summary_finished(job_id)
            return
        if job.summary_status not in {"queued", "running"}:
            now = datetime.now(timezone.utc)
            job.summary_status = "queued"
            job.summary_error = None
            job.summary_model = config.selected_model
            job.summary_queued_at = now
            job.summary_started_at = None
            job.summary_finished_at = None
            job.summary_updated_at = now
            await db.commit()
            emit_summary_event(job.owner_user_id, job_id)
    if not config.enabled or not requested or not config.selected_model:
        return
    queue_summary_job(job_id)


def queue_summary_job(job_id: int) -> None:
    existing = _active_summary_tasks.get(job_id)
    if existing and not existing.done():
        return
    task = asyncio.create_task(_run_queued_summary(job_id))
    _active_summary_tasks[job_id] = task
    task.add_done_callback(lambda _task: _active_summary_tasks.pop(job_id, None))


def cancel_summary_job(job_id: int) -> bool:
    task = _active_summary_tasks.get(job_id)
    if not task or task.done():
        return False
    task.cancel()
    return True


async def _run_queued_summary(job_id: int) -> None:
    try:
        async with _summary_run_lock:
            await summarize_job(job_id)
    except asyncio.CancelledError:
        await mark_summary_cancelled(job_id)
        raise
    except Exception:
        logger.exception("Background summarization failed for job %s", job_id)


async def mark_summary_cancelled(job_id: int) -> None:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job or job.summary_status not in {"queued", "running"}:
            return
        job.summary_status = "cancelled"
        job.summary_error = None
        job.summary_finished_at = now
        job.summary_updated_at = now
        await db.commit()
        emit_summary_event(job.owner_user_id, job_id)
    await _notify_telegram_summary_finished(job_id)


async def _notify_telegram_summary_finished(job_id: int) -> None:
    try:
        from app.services.telegram_bot import notify_summary_finished  # type: ignore[attr-defined]

        await notify_summary_finished(job_id)
    except ImportError:
        return
    except Exception:
        logger.exception("Telegram summary notification failed for job %s", job_id)


def _split_text(text: str, limit: int = _CHUNK_CHAR_LIMIT) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= limit:
        return [normalized] if normalized else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in normalized.split("\n"):
        paragraph_len = len(paragraph)
        if current and current_len + paragraph_len + 1 > limit:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
        if paragraph_len > limit:
            for start in range(0, paragraph_len, limit):
                chunk = paragraph[start : start + limit].strip()
                if chunk:
                    chunks.append(chunk)
            continue
        current.append(paragraph)
        current_len += paragraph_len + 1
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _chunk_prompt(config: SummarizationSettings, chunk: str, index: int, total: int) -> str:
    return (
        f"This is transcript chunk {index} of {total}. Summarize only this chunk and preserve important names, dates, decisions, and action items.\n\n"
        f"Transcript chunk:\n{chunk}"
    )


def _final_prompt(config: SummarizationSettings, summaries: list[str]) -> str:
    joined = "\n\n".join(f"Chunk {index + 1} summary:\n{summary}" for index, summary in enumerate(summaries))
    return (
        "Combine these chunk summaries into one final transcript summary. Remove duplication and keep the result concise.\n\n"
        f"{joined}"
    )


async def _ollama_generate(config: SummarizationSettings, prompt: str) -> str:
    async with httpx.AsyncClient(
        base_url=config.ollama_base_url,
        timeout=httpx.Timeout(_OLLAMA_TIMEOUT_SECONDS),
    ) as client:
        response = await client.post(
            "/api/generate",
            json={
                "model": config.selected_model,
                "system": config.system_prompt,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx": _OLLAMA_CONTEXT_TOKENS,
                    "num_predict": _OLLAMA_NUM_PREDICT,
                },
            },
        )
        response.raise_for_status()
        payload: Any = response.json()
    text = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise SummarizationError("Ollama returned an empty summary")
    return text.strip()


async def _summarize_text(config: SummarizationSettings, text: str) -> str:
    chunks = _split_text(text)
    if not chunks:
        raise SummarizationError("Transcript is empty")
    if len(chunks) == 1:
        return await _ollama_generate(config, _chunk_prompt(config, chunks[0], 1, 1))

    partials: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        partials.append(await _ollama_generate(config, _chunk_prompt(config, chunk, index, len(chunks))))
    return await _ollama_generate(config, _final_prompt(config, partials))


async def summarize_job(job_id: int) -> None:
    async with async_session_factory() as db:
        config = await get_summarization_settings(db)
        result = await db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        validation_error = None
        if not config.enabled:
            validation_error = "Summarization is disabled"
        elif not config.selected_model:
            validation_error = "No summarization model selected"
        elif job.status != "succeeded" or not job.transcript_text:
            validation_error = "Only finished transcriptions with text can be summarized"
        if validation_error:
            job.summary_status = "failed"
            job.summary_error = validation_error
            job.summary_model = config.selected_model or job.summary_model
            now = datetime.now(timezone.utc)
            job.summary_finished_at = now
            job.summary_updated_at = now
            await db.commit()
            await _notify_telegram_summary_finished(job_id)
            return

        if job.summary_status == "cancelled":
            return

        now = datetime.now(timezone.utc)
        job.summary_status = "running"
        job.summary_error = None
        job.summary_model = config.selected_model
        job.summary_started_at = now
        job.summary_finished_at = None
        job.summary_updated_at = now
        await db.commit()
        emit_summary_event(job.owner_user_id, job_id)
        transcript_text = job.transcript_text

    try:
        summary = await _summarize_text(config, transcript_text)
    except Exception as exc:
        error = _summary_error_message(exc)
        async with async_session_factory() as db:
            result = await db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                if job.summary_status == "cancelled":
                    return
                now = datetime.now(timezone.utc)
                job.summary_status = "failed"
                job.summary_error = error
                job.summary_model = config.selected_model
                job.summary_finished_at = now
                job.summary_updated_at = now
                await db.commit()
                emit_summary_event(job.owner_user_id, job_id)
        await _notify_telegram_summary_finished(job_id)
        return

    async with async_session_factory() as db:
        result = await db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            if job.summary_status == "cancelled":
                return
            now = datetime.now(timezone.utc)
            job.summary_text = summary
            job.summary_status = "succeeded"
            job.summary_error = None
            job.summary_model = config.selected_model
            job.summary_finished_at = now
            job.summary_updated_at = now
            await db.commit()
            emit_summary_event(job.owner_user_id, job_id)
    await _notify_telegram_summary_finished(job_id)


def _summary_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"Ollama request timed out after {_OLLAMA_TIMEOUT_SECONDS} seconds"
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text.strip()
        if detail:
            detail = detail[:500]
            return f"Ollama returned HTTP {exc.response.status_code}: {detail}"
        return f"Ollama returned HTTP {exc.response.status_code}"
    message = str(exc).strip()
    return message or exc.__class__.__name__
