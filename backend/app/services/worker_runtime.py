from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_job_chunk import TranscriptionJobChunk
from app.models.transcription_model import TranscriptionModel
from app.models.transcription_worker import TranscriptionWorker
from app.schemas.workers import WorkerClaimOut, WorkerHeartbeatIn, WorkerModelSpeedStat, WorkerModelState
from app.services.model_catalog import get_catalog_item


def worker_is_online(worker: TranscriptionWorker, now: datetime | None = None) -> bool:
    if not worker.last_heartbeat_at:
        return False
    now = now or datetime.now(timezone.utc)
    heartbeat = worker.last_heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    return now - heartbeat <= timedelta(seconds=settings.asr_worker_offline_seconds)


def model_states_from_json(value: str | None) -> list[WorkerModelState]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    states: list[WorkerModelState] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                states.append(WorkerModelState(**item))
            except Exception:
                continue
    return states


def model_states_to_json(states: list[WorkerModelState]) -> str:
    return json.dumps([state.model_dump() for state in states], ensure_ascii=False)


def model_speed_stats_from_json(value: str | None) -> list[WorkerModelSpeedStat]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    stats: list[WorkerModelSpeedStat] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                stats.append(WorkerModelSpeedStat(**item))
            except Exception:
                continue
    return stats


def model_speed_stats_to_json(stats: list[WorkerModelSpeedStat]) -> str:
    return json.dumps([item.model_dump() for item in stats], ensure_ascii=False)


def worker_model_speed(worker: TranscriptionWorker, variant: str) -> float | None:
    variant = _catalog_install_variant(variant)
    for item in model_speed_stats_from_json(worker.model_speed_stats_json):
        if item.variant == variant and item.total_audio_seconds > 0 and item.total_runtime_seconds > 0:
            return float(item.total_audio_seconds) / float(item.total_runtime_seconds)
    return None


def add_worker_model_speed_sample(
    worker: TranscriptionWorker,
    variant: str | None,
    runtime_seconds: float | None,
    audio_seconds: float | None,
) -> None:
    if not variant or not runtime_seconds or not audio_seconds:
        return
    if runtime_seconds <= 0 or audio_seconds <= 0:
        return
    variant = _catalog_install_variant(variant)
    stats = model_speed_stats_from_json(worker.model_speed_stats_json)
    by_variant = {item.variant: item for item in stats}
    item = by_variant.get(variant)
    if item is None:
        item = WorkerModelSpeedStat(variant=variant)
        stats.append(item)
    item.completed_count += 1
    item.total_runtime_seconds += float(runtime_seconds)
    item.total_audio_seconds += float(audio_seconds)
    item.runtime_per_audio_hour_seconds = (
        item.total_runtime_seconds / item.total_audio_seconds * 3600
        if item.total_audio_seconds > 0
        else None
    )
    stats.sort(key=lambda value: value.variant)
    worker.model_speed_stats_json = model_speed_stats_to_json(stats)


def installed_variants(states: list[WorkerModelState]) -> set[str]:
    return {state.variant for state in states if state.status == "installed"}


def worker_model_variants(worker: TranscriptionWorker) -> set[str]:
    return installed_variants(model_states_from_json(worker.model_inventory_json))


def requested_installs_from_json(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def requested_installs_to_json(variants: list[str]) -> str:
    seen: set[str] = set()
    clean: list[str] = []
    for variant in variants:
        value = variant.strip()
        if value and value not in seen:
            seen.add(value)
            clean.append(value)
    return json.dumps(clean, ensure_ascii=False)


def requested_uninstalls_from_json(value: str | None) -> list[str]:
    return requested_installs_from_json(value)


def requested_uninstalls_to_json(variants: list[str]) -> str:
    return requested_installs_to_json(variants)


def _catalog_install_variant(variant: str) -> str:
    catalog_item = get_catalog_item(variant)
    if not catalog_item:
        return variant
    return catalog_item.model_variant or catalog_item.variant


def split_worker_ids(job: TranscriptionJob) -> set[int]:
    if not job.split_worker_ids_json:
        return set()
    try:
        raw = json.loads(job.split_worker_ids_json)
    except json.JSONDecodeError:
        return set()
    if not isinstance(raw, list):
        return set()
    ids: set[int] = set()
    for value in raw:
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


async def upsert_worker(
    db: AsyncSession,
    body: WorkerHeartbeatIn,
    *,
    accepted_default: bool = False,
) -> TranscriptionWorker:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TranscriptionWorker).where(TranscriptionWorker.name == body.name)
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        worker = TranscriptionWorker(name=body.name, accepted=accepted_default)
        db.add(worker)
        await db.flush()
    elif worker.is_deleted:
        worker.is_deleted = False
        worker.accepted = accepted_default

    worker.status = body.status if worker.accepted else "pending"
    worker.last_heartbeat_at = now
    worker.current_job_count = max(0, body.current_job_count)
    worker.model_inventory_json = model_states_to_json(body.models)
    worker.install_status_json = model_states_to_json(body.installs)
    installed = installed_variants(body.models)
    requested = [
        variant
        for variant in requested_installs_from_json(worker.requested_installs_json)
        if variant not in installed and _catalog_install_variant(variant) not in installed
    ]
    worker.requested_installs_json = requested_installs_to_json(requested)
    requested_uninstalls = [
        variant
        for variant in requested_uninstalls_from_json(worker.requested_uninstalls_json)
        if variant in installed or _catalog_install_variant(variant) in installed
    ]
    worker.requested_uninstalls_json = requested_uninstalls_to_json(requested_uninstalls)
    worker.last_error = body.last_error
    worker.auto_install_models = body.auto_install_models
    worker.updated_at = now
    await db.commit()
    await db.refresh(worker)
    return worker


async def list_workers(db: AsyncSession) -> list[TranscriptionWorker]:
    result = await db.execute(
        select(TranscriptionWorker)
        .where(TranscriptionWorker.is_deleted.is_not(True))
        .order_by(
            TranscriptionWorker.last_heartbeat_at.desc().nullslast(),
            TranscriptionWorker.name,
        )
    )
    return result.scalars().all()


def _catalog_variant_for_model(model: TranscriptionModel) -> str:
    catalog_item = get_catalog_item(model.variant)
    return catalog_item.model_variant if catalog_item and catalog_item.model_variant else model.variant


def _claim_response_for_job(job: TranscriptionJob, kind: str, chunk: TranscriptionJobChunk | None = None) -> WorkerClaimOut:
    catalog_variant = _catalog_variant_for_model(job.model)
    catalog_item = get_catalog_item(job.model.variant) or get_catalog_item(catalog_variant)
    return WorkerClaimOut(
        kind=kind,
        job_id=job.id,
        chunk_id=chunk.id if chunk else None,
        audio_file_id=job.audio_file_id,
        model_id=job.model_id,
        model_variant=catalog_variant,
        model_download_url=catalog_item.download_url if catalog_item else job.model.download_url,
        language=job.language,
        owner_user_id=job.owner_user_id,
        start_seconds=chunk.start_seconds if chunk else None,
        end_seconds=chunk.end_seconds if chunk else None,
        cancel_requested=job.cancel_requested_at is not None,
    )


async def _worker_for_claim(db: AsyncSession, name: str, models: list[WorkerModelState], auto_install: bool) -> TranscriptionWorker:
    heartbeat = WorkerHeartbeatIn(
        name=name,
        status="idle",
        current_job_count=0,
        models=models,
        installs=[],
        auto_install_models=auto_install,
    )
    return await upsert_worker(db, heartbeat)


async def claim_next_work(
    db: AsyncSession,
    name: str,
    models: list[WorkerModelState],
    auto_install: bool,
) -> WorkerClaimOut:
    worker = await _worker_for_claim(db, name, models, auto_install)
    if not worker.accepted or worker.is_deleted:
        return WorkerClaimOut()
    variants = installed_variants(models)
    now = datetime.now(timezone.utc)

    chunk_result = await db.execute(
        select(TranscriptionJobChunk)
        .join(TranscriptionJobChunk.parent_job)
        .join(TranscriptionJob.model)
        .options(
            selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.model),
            selectinload(TranscriptionJobChunk.parent_job).selectinload(TranscriptionJob.chunks),
        )
        .where(
            TranscriptionJobChunk.status == "queued",
            TranscriptionJob.status.in_(["queued", "running"]),
            TranscriptionJob.cancel_requested_at.is_(None),
        )
        .order_by(TranscriptionJob.created_at, TranscriptionJobChunk.index)
    )
    for chunk in chunk_result.scalars().all():
        job = chunk.parent_job
        allowed_split_workers = split_worker_ids(job)
        if allowed_split_workers and worker.id not in allowed_split_workers:
            continue
        if job.preferred_worker_id is not None and job.preferred_worker_id != worker.id:
            continue
        required_variant = _catalog_variant_for_model(job.model)
        if required_variant not in variants:
            continue
        upd = await db.execute(
            update(TranscriptionJobChunk)
            .where(
                TranscriptionJobChunk.id == chunk.id,
                TranscriptionJobChunk.status == "queued",
            )
            .values(
                status="running",
                status_text="Preparing audio chunk",
                worker_id=worker.id,
                worker_name_snapshot=worker.name,
                claimed_at=now,
                started_at=now,
            )
        )
        if upd.rowcount != 1:
            await db.rollback()
            continue
        await db.execute(
            update(TranscriptionJob)
            .where(TranscriptionJob.id == job.id)
            .values(
                status="running",
                status_text="Split transcription running",
                split_status="running",
                started_at=job.started_at or now,
                worker_heartbeat_at=now,
            )
        )
        worker.status = "running"
        worker.current_job_count = 1
        worker.updated_at = now
        await db.commit()
        await db.refresh(chunk, attribute_names=["parent_job"])
        return _claim_response_for_job(job, "chunk", chunk)

    job_result = await db.execute(
        select(TranscriptionJob)
        .options(selectinload(TranscriptionJob.model))
        .where(
            TranscriptionJob.status == "queued",
            TranscriptionJob.split_enabled.is_not(True),
            TranscriptionJob.cancel_requested_at.is_(None),
        )
        .order_by(TranscriptionJob.created_at, TranscriptionJob.id)
    )
    for job in job_result.scalars().all():
        if job.preferred_worker_id is not None and job.preferred_worker_id != worker.id:
            continue
        if _catalog_variant_for_model(job.model) not in variants:
            continue
        upd = await db.execute(
            update(TranscriptionJob)
            .where(
                TranscriptionJob.id == job.id,
                TranscriptionJob.status == "queued",
                TranscriptionJob.split_enabled.is_not(True),
            )
            .values(
                status="running",
                status_text="Preparing audio",
                started_at=now,
                claimed_at=now,
                worker_id=worker.id,
                worker_name_snapshot=worker.name,
                worker_heartbeat_at=now,
            )
        )
        if upd.rowcount != 1:
            await db.rollback()
            continue
        worker.status = "running"
        worker.current_job_count = 1
        worker.updated_at = now
        await db.commit()
        return _claim_response_for_job(job, "job")

    requested_uninstall = await _next_requested_uninstall(db, worker, variants)
    if requested_uninstall is not None:
        return requested_uninstall

    requested_install = await _next_requested_install(db, worker, variants)
    if requested_install is not None:
        return requested_install

    if auto_install:
        install = await _next_model_to_install(db, variants, worker.id)
        if install is not None:
            return install
    return WorkerClaimOut()


async def _next_requested_install(
    db: AsyncSession,
    worker: TranscriptionWorker,
    installed: set[str],
) -> WorkerClaimOut | None:
    requested = requested_installs_from_json(worker.requested_installs_json)
    for variant in requested:
        install_variant = _catalog_install_variant(variant)
        if variant in installed or install_variant in installed:
            continue
        catalog_item = get_catalog_item(variant)
        if not catalog_item:
            continue
        worker.status = "installing"
        worker.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return WorkerClaimOut(
            kind="install",
            model_variant=install_variant,
            model_download_url=catalog_item.download_url,
        )
    return None


async def _next_requested_uninstall(
    db: AsyncSession,
    worker: TranscriptionWorker,
    installed: set[str],
) -> WorkerClaimOut | None:
    requested = requested_uninstalls_from_json(worker.requested_uninstalls_json)
    for variant in requested:
        uninstall_variant = _catalog_install_variant(variant)
        if variant not in installed and uninstall_variant not in installed:
            continue
        worker.status = "uninstalling"
        worker.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return WorkerClaimOut(
            kind="uninstall",
            model_variant=uninstall_variant,
        )
    return None


async def _next_model_to_install(
    db: AsyncSession,
    installed: set[str],
    worker_id: int,
) -> WorkerClaimOut | None:
    result = await db.execute(
        select(TranscriptionJob)
        .options(selectinload(TranscriptionJob.model))
        .where(TranscriptionJob.status == "queued")
        .where(TranscriptionJob.cancel_requested_at.is_(None))
        .order_by(TranscriptionJob.created_at, TranscriptionJob.id)
    )
    for job in result.scalars().all():
        allowed_split_workers = split_worker_ids(job)
        if allowed_split_workers and worker_id not in allowed_split_workers:
            continue
        if job.preferred_worker_id is not None and job.preferred_worker_id != worker_id:
            continue
        variant = _catalog_variant_for_model(job.model)
        if variant in installed:
            continue
        catalog_item = get_catalog_item(job.model.variant) or get_catalog_item(variant)
        if not catalog_item:
            continue
        return WorkerClaimOut(
            kind="install",
            model_id=job.model_id,
            model_variant=variant,
            model_download_url=catalog_item.download_url,
        )
    return None


async def _model_worker_speed_by_worker_id(
    db: AsyncSession,
    model_id: int,
    worker_ids: set[int],
) -> dict[int, float]:
    if not worker_ids:
        return {}

    samples: dict[int, list[float]] = {worker_id: [] for worker_id in worker_ids}
    normal_result = await db.execute(
        select(
            TranscriptionJob.worker_id,
            TranscriptionJob.started_at,
            TranscriptionJob.finished_at,
            AudioFile.duration_seconds,
        )
        .join(AudioFile, AudioFile.id == TranscriptionJob.audio_file_id)
        .where(
            TranscriptionJob.model_id == model_id,
            TranscriptionJob.worker_id.in_(worker_ids),
            TranscriptionJob.status == "succeeded",
            TranscriptionJob.split_enabled.is_not(True),
            TranscriptionJob.started_at.is_not(None),
            TranscriptionJob.finished_at.is_not(None),
            AudioFile.duration_seconds.is_not(None),
            AudioFile.duration_seconds > 0,
        )
    )
    for worker_id, started_at, finished_at, audio_seconds in normal_result.all():
        runtime_seconds = (finished_at - started_at).total_seconds()
        if worker_id is not None and runtime_seconds > 0 and audio_seconds and audio_seconds > 0:
            samples.setdefault(worker_id, []).append(float(audio_seconds) / runtime_seconds)

    chunk_result = await db.execute(
        select(
            TranscriptionJobChunk.worker_id,
            TranscriptionJobChunk.started_at,
            TranscriptionJobChunk.finished_at,
            TranscriptionJobChunk.start_seconds,
            TranscriptionJobChunk.end_seconds,
            TranscriptionJobChunk.overlap_start_seconds,
            TranscriptionJobChunk.overlap_end_seconds,
        )
        .join(TranscriptionJob, TranscriptionJob.id == TranscriptionJobChunk.parent_job_id)
        .where(
            TranscriptionJob.model_id == model_id,
            TranscriptionJobChunk.worker_id.in_(worker_ids),
            TranscriptionJobChunk.status == "succeeded",
            TranscriptionJobChunk.started_at.is_not(None),
            TranscriptionJobChunk.finished_at.is_not(None),
            TranscriptionJobChunk.end_seconds > TranscriptionJobChunk.start_seconds,
        )
    )
    for worker_id, started_at, finished_at, start_seconds, end_seconds, overlap_start, overlap_end in chunk_result.all():
        runtime_seconds = (finished_at - started_at).total_seconds()
        audio_seconds = max(
            0.0,
            float(end_seconds)
            - float(start_seconds)
            - float(overlap_start or 0.0)
            - float(overlap_end or 0.0),
        )
        if worker_id is not None and runtime_seconds > 0 and audio_seconds > 0:
            samples.setdefault(worker_id, []).append(audio_seconds / runtime_seconds)

    return {
        worker_id: sum(values) / len(values)
        for worker_id, values in samples.items()
        if values
    }


async def _split_core_durations_for_workers(
    db: AsyncSession,
    job: TranscriptionJob,
    workers: list[TranscriptionWorker],
    duration: float,
    chunk_count: int,
) -> list[float]:
    if not workers or len(workers) != chunk_count:
        return [duration / chunk_count for _ in range(chunk_count)]

    model_speeds = await _model_worker_speed_by_worker_id(db, job.model_id, {worker.id for worker in workers})
    model_variant = _catalog_variant_for_model(job.model)
    weights: list[float] = []
    for worker in workers:
        speed = model_speeds.get(worker.id)
        if speed is None:
            speed = worker_model_speed(worker, model_variant)
        weights.append(speed if speed and speed > 0 else 1.0)

    total_weight = sum(weights)
    if total_weight <= 0:
        return [duration / chunk_count for _ in range(chunk_count)]

    durations = [(duration * weight) / total_weight for weight in weights]
    rounding_delta = duration - sum(durations)
    durations[-1] += rounding_delta
    return durations


async def create_split_chunks(db: AsyncSession, job: TranscriptionJob) -> None:
    if not job.audio_file or not job.audio_file.duration_seconds:
        job.split_status = "failed"
        job.status = "failed"
        job.status_text = "Split transcription failed"
        job.error_message = "Audio duration is required for split transcription."
        return

    configured_split_workers = list(dict.fromkeys(split_worker_ids(job)))
    planned_workers: list[TranscriptionWorker] = []
    if configured_split_workers:
        worker_result = await db.execute(
            select(TranscriptionWorker).where(
                TranscriptionWorker.id.in_(configured_split_workers),
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        workers_by_id = {worker.id: worker for worker in worker_result.scalars().all()}
        planned_workers = [workers_by_id[worker_id] for worker_id in configured_split_workers if worker_id in workers_by_id]
        desired = len(planned_workers) or len(configured_split_workers)
    else:
        online_workers = await db.execute(
            select(TranscriptionWorker).where(
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        planned_workers = [worker for worker in online_workers.scalars().all() if worker_is_online(worker)]
        desired = max(2, len(planned_workers) or 2)
    duration = float(job.audio_file.duration_seconds)
    max_by_duration = max(1, math.floor(duration / max(1, settings.asr_split_min_chunk_seconds)))
    chunk_count = min(settings.asr_split_max_chunks, desired, max_by_duration)
    if chunk_count < 2:
        chunk_count = 2 if duration >= 60 else 1

    if chunk_count <= 1:
        job.split_enabled = False
        job.split_status = None
        return

    if planned_workers and len(planned_workers) > chunk_count:
        planned_workers = planned_workers[:chunk_count]
    elif len(planned_workers) < chunk_count:
        planned_workers = []

    chunk_durations = await _split_core_durations_for_workers(db, job, planned_workers, duration, chunk_count)
    overlap = max(0.0, float(settings.asr_split_overlap_seconds))
    core_start = 0.0
    for index in range(chunk_count):
        core_end = duration if index == chunk_count - 1 else min(duration, core_start + chunk_durations[index])
        worker = planned_workers[index] if planned_workers else None
        chunk = TranscriptionJobChunk(
            parent_job_id=job.id,
            index=index,
            start_seconds=max(0.0, core_start - (overlap if index else 0.0)),
            end_seconds=min(duration, core_end + (overlap if index < chunk_count - 1 else 0.0)),
            overlap_start_seconds=overlap if index else 0.0,
            overlap_end_seconds=overlap if index < chunk_count - 1 else 0.0,
            status="queued",
            status_text=f"Waiting for {worker.display_name or worker.name}" if worker else "Waiting for worker",
            worker_id=worker.id if worker else None,
            worker_name_snapshot=worker.name if worker else None,
        )
        db.add(chunk)
        core_start = core_end
    job.split_status = "queued"


def _seconds_to_stamp(seconds: float, separator: str) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms -= 1000
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    return f"{h:02d}:{m:02d}:{s:02d}{separator}{ms:03d}"


def _segment_seconds(segment: dict[str, Any], key: str) -> float | None:
    offsets = segment.get("offsets")
    if isinstance(offsets, dict):
        raw = offsets.get("from" if key == "start" else "to")
        if isinstance(raw, (int, float)):
            return max(0.0, float(raw) / 1000)
    timestamps = segment.get("timestamps")
    if isinstance(timestamps, dict):
        raw = timestamps.get("from" if key == "start" else "to")
        if isinstance(raw, str):
            normalized = raw.replace(",", ".")
            parts = normalized.split(":")
            if len(parts) == 3:
                try:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                except ValueError:
                    return None
    return None


def _segments_from_chunk(chunk: TranscriptionJobChunk) -> list[dict[str, Any]]:
    if not chunk.output_json:
        return []
    try:
        data = json.loads(chunk.output_json)
    except json.JSONDecodeError:
        return []
    raw = data.get("transcription") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    merged: list[dict[str, Any]] = []
    for segment in raw:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        start = _segment_seconds(segment, "start")
        end = _segment_seconds(segment, "end")
        if not text or start is None or end is None:
            continue
        global_start = chunk.start_seconds + start
        global_end = chunk.start_seconds + end
        if global_end <= chunk.start_seconds + chunk.overlap_start_seconds:
            continue
        if global_start >= chunk.end_seconds - chunk.overlap_end_seconds:
            continue
        item = {
            "timestamps": {
                "from": _seconds_to_stamp(global_start, ","),
                "to": _seconds_to_stamp(global_end, ","),
            },
            "offsets": {
                "from": int(round(global_start * 1000)),
                "to": int(round(max(global_start, global_end) * 1000)),
            },
            "text": text,
        }
        if not merged or merged[-1]["text"].strip().lower() != text.lower():
            merged.append(item)
    return merged


def _srt_from_segments(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        blocks.append(
            f"{index}\n{_seconds_to_stamp(start, ',')} --> {_seconds_to_stamp(end, ',')}\n{segment['text']}"
        )
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _vtt_from_segments(segments: list[dict[str, Any]]) -> str:
    blocks = ["WEBVTT"]
    for segment in segments:
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        blocks.append(
            f"{_seconds_to_stamp(start, '.')} --> {_seconds_to_stamp(end, '.')}\n{segment['text']}"
        )
    return "\n\n".join(blocks).strip() + "\n"


async def try_merge_split_job(db: AsyncSession, job_id: int) -> None:
    result = await db.execute(
        select(TranscriptionJob)
        .options(
            selectinload(TranscriptionJob.chunks),
            selectinload(TranscriptionJob.audio_file),
        )
        .where(TranscriptionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job or not job.split_enabled or not job.chunks:
        return
    terminal_statuses = {"succeeded", "failed", "cancelled"}
    all_chunks_terminal = all(chunk.status in terminal_statuses for chunk in job.chunks)
    if job.cancel_requested_at:
        if all_chunks_terminal:
            job.status = "cancelled"
            job.split_status = "cancelled"
            job.status_text = "Cancelled"
            job.error_message = None
            job.finished_at = datetime.now(timezone.utc)
        else:
            job.status = "running"
            job.split_status = "running"
            job.status_text = "Cancelling…"
            job.error_message = None
        await db.commit()
        return
    if any(chunk.status == "failed" for chunk in job.chunks):
        job.status = "failed"
        job.split_status = "failed"
        job.status_text = "Split transcription failed"
        job.error_message = next((chunk.error_message for chunk in job.chunks if chunk.error_message), None)
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return
    if not all(chunk.status == "succeeded" for chunk in job.chunks):
        completed = sum(1 for chunk in job.chunks if chunk.status == "succeeded")
        total = len(job.chunks)
        job.status = "running" if completed else "queued"
        job.split_status = "running" if completed else "queued"
        job.status_text = f"Split transcription {completed}/{total} chunks"
        await db.commit()
        return

    segments: list[dict[str, Any]] = []
    for chunk in sorted(job.chunks, key=lambda item: item.index):
        segments.extend(_segments_from_chunk(chunk))

    output_dir = settings.outputs_dir / str(job.owner_user_id) / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "transcript.txt"
    json_path = output_dir / "transcript.json"
    srt_path = output_dir / "transcript.srt"
    vtt_path = output_dir / "transcript.vtt"

    transcript_text = "\n".join(str(segment.get("text", "")).strip() for segment in segments).strip()
    txt_path.write_text(transcript_text + ("\n" if transcript_text else ""), encoding="utf-8")
    json_path.write_text(
        json.dumps({"transcription": segments}, ensure_ascii=False, indent="\t") + "\n",
        encoding="utf-8",
    )
    srt_path.write_text(_srt_from_segments(segments), encoding="utf-8")
    vtt_path.write_text(_vtt_from_segments(segments), encoding="utf-8")

    job.transcript_text = transcript_text
    job.output_txt_path = str(txt_path)
    job.output_json_path = str(json_path)
    job.output_srt_path = str(srt_path)
    job.output_vtt_path = str(vtt_path)
    job.status = "succeeded"
    job.status_text = "Split transcription finished"
    job.split_status = "merged"
    job.error_message = None
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()


def parse_progress_percent(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d{1,3})%", text)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))
