from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_model import TranscriptionModel
from app.models.transcription_worker import TranscriptionWorker
from app.schemas.telegram_settings import (
    TelegramAllowedUser,
    TelegramBotSettings,
    TelegramBotSettingsUpdate,
    TelegramBotStatus,
)
from app.services.audio_svc import is_supported_audio, probe_duration_seconds
from app.services.model_catalog import get_catalog_item
from app.services.telegram_settings import (
    get_telegram_bot_settings,
    get_telegram_update_offset,
    set_telegram_update_offset,
    token_preview,
    update_telegram_bot_settings,
)
from app.services.worker_runtime import create_split_chunks, model_states_from_json, worker_is_online

logger = logging.getLogger(__name__)
_poll_task: asyncio.Task | None = None
_stopping = False
_client: httpx.AsyncClient | None = None
_client_proxy_url: str | None = None
_last_poll_at: datetime | None = None
_last_error: str | None = None


class TelegramTransportError(RuntimeError):
    pass


@dataclass
class TelegramAttachment:
    file_id: str
    filename: str
    mime_type: str | None = None
    file_size: int | None = None


def _telegram_client(config: TelegramBotSettings) -> httpx.AsyncClient:
    global _client, _client_proxy_url
    proxy_url = config.proxy_url
    if _client is None or _client_proxy_url != proxy_url:
        if _client is not None:
            asyncio.create_task(_client.aclose())
        transport_kwargs: dict[str, Any] = {}
        if proxy_url:
            transport_kwargs["proxy"] = proxy_url
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0, read=60.0),
            transport=httpx.AsyncHTTPTransport(**transport_kwargs),
        )
        _client_proxy_url = proxy_url
    return _client


async def close_telegram_http_client() -> None:
    global _client, _client_proxy_url
    if _client is not None:
        await _client.aclose()
    _client = None
    _client_proxy_url = None


async def telegram_api_request(
    config: TelegramBotSettings,
    http_method: str,
    api_method: str,
    **kwargs: Any,
) -> httpx.Response:
    if not config.bot_token:
        raise TelegramTransportError("Telegram bot token is not configured")
    url = f"https://api.telegram.org/bot{config.bot_token}/{api_method}"
    try:
        return await _telegram_client(config).request(http_method, url, **kwargs)
    except httpx.HTTPError as exc:
        route = "proxy" if config.proxy_url else "direct"
        raise TelegramTransportError(f"Telegram {route} transport error: {exc}") from exc


async def get_bot_status() -> TelegramBotStatus:
    async with async_session_factory() as db:
        config = await get_telegram_bot_settings(db)
        offset = await get_telegram_update_offset(db)
    task_active = _poll_task is not None and not _poll_task.done()
    return TelegramBotStatus(
        running=config.enabled and task_active,
        enabled=config.enabled,
        token_configured=bool(config.bot_token),
        token_preview=token_preview(config.bot_token),
        last_poll_at=_last_poll_at,
        last_error=_last_error,
        update_offset=offset,
    )


async def start_telegram_bot() -> None:
    global _poll_task, _stopping
    _stopping = False
    current_loop = asyncio.get_running_loop()
    if _poll_task is None or _poll_task.done() or _poll_task.get_loop() is not current_loop:
        _poll_task = asyncio.create_task(_poll_loop())


async def stop_telegram_bot() -> None:
    global _stopping
    _stopping = True
    if _poll_task:
        _poll_task.cancel()
        if _poll_task.get_loop() is asyncio.get_running_loop():
            try:
                await _poll_task
            except asyncio.CancelledError:
                pass
    await close_telegram_http_client()


async def restart_telegram_bot() -> None:
    await stop_telegram_bot()
    await start_telegram_bot()


async def _poll_loop() -> None:
    global _last_poll_at, _last_error
    while not _stopping:
        try:
            async with async_session_factory() as db:
                config = await get_telegram_bot_settings(db)
                offset = await get_telegram_update_offset(db)
            if not config.enabled:
                await asyncio.sleep(5)
                continue
            if not config.bot_token or config.default_model_id is None or not config.allowed_users:
                _last_error = "Telegram bot is enabled but not fully configured"
                await asyncio.sleep(10)
                continue

            params: dict[str, Any] = {
                "timeout": 25,
                "allowed_updates": '["message"]',
            }
            if offset is not None:
                params["offset"] = offset
            response = await telegram_api_request(config, "GET", "getUpdates", params=params)
            _last_poll_at = datetime.now(timezone.utc)
            if response.status_code != 200:
                _last_error = f"Telegram getUpdates failed: {response.text[:500]}"
                await asyncio.sleep(5)
                continue
            payload = response.json()
            if not payload.get("ok"):
                _last_error = f"Telegram getUpdates failed: {payload}"
                await asyncio.sleep(5)
                continue
            _last_error = None
            for update in payload.get("result", []):
                update_id = update.get("update_id")
                try:
                    await _handle_update(config, update)
                except Exception:
                    logger.exception("Telegram update handling failed")
                if isinstance(update_id, int):
                    async with async_session_factory() as db:
                        await set_telegram_update_offset(db, update_id + 1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _last_error = str(exc)
            logger.exception("Telegram polling failed")
            await asyncio.sleep(10)


def _chat_id(message: dict[str, Any]) -> str | None:
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    raw = chat.get("id")
    return str(raw) if raw is not None else None


def _sender_id(message: dict[str, Any]) -> int | None:
    sender = message.get("from")
    if not isinstance(sender, dict):
        return None
    raw = sender.get("id")
    return raw if isinstance(raw, int) else None


def _message_text(message: dict[str, Any]) -> str:
    value = message.get("text")
    return value.strip() if isinstance(value, str) else ""


def _parse_command(text: str) -> tuple[str, str] | None:
    if not text.startswith("/"):
        return None
    first, _, rest = text.partition(" ")
    command = first[1:].split("@", 1)[0].lower()
    return command, rest.strip()


def _catalog_install_variant(variant: str) -> str:
    catalog_item = get_catalog_item(variant)
    if not catalog_item:
        return variant
    return catalog_item.model_variant or catalog_item.variant


def _worker_label(worker: TranscriptionWorker) -> str:
    return worker.display_name or worker.name


def _worker_variants(worker: TranscriptionWorker) -> set[str]:
    return {state.variant for state in model_states_from_json(worker.model_inventory_json)}


def _worker_state(worker: TranscriptionWorker, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not worker_is_online(worker, now):
        return "offline"
    if worker.current_job_count > 0 or worker.status != "idle":
        return "busy"
    return "free"


def _attachment_from_message(message: dict[str, Any]) -> TelegramAttachment | None:
    audio = message.get("audio")
    if isinstance(audio, dict):
        filename = audio.get("file_name") or f"telegram_audio_{audio.get('file_unique_id') or uuid4().hex}.mp3"
        return TelegramAttachment(
            file_id=audio["file_id"],
            filename=filename,
            mime_type=audio.get("mime_type"),
            file_size=audio.get("file_size"),
        )
    voice = message.get("voice")
    if isinstance(voice, dict):
        return TelegramAttachment(
            file_id=voice["file_id"],
            filename=f"telegram_voice_{voice.get('file_unique_id') or uuid4().hex}.ogg",
            mime_type=voice.get("mime_type") or "audio/ogg",
            file_size=voice.get("file_size"),
        )
    document = message.get("document")
    if isinstance(document, dict):
        filename = document.get("file_name") or f"telegram_document_{document.get('file_unique_id') or uuid4().hex}"
        mime_type = document.get("mime_type")
        if not ((mime_type or "").startswith("audio/") or is_supported_audio(filename)):
            return None
        return TelegramAttachment(
            file_id=document["file_id"],
            filename=filename,
            mime_type=mime_type,
            file_size=document.get("file_size"),
        )
    return None


async def _handle_command(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
    command: str,
    argument: str,
) -> None:
    if command in {"start", "help"}:
        await send_telegram_message(
            config,
            chat_id,
            "Commands:\n"
            "/workers - list available workers\n"
            "/setworker <id or name> - choose worker for your Telegram jobs\n"
            "/models - list models available for your selected worker\n"
            "/setmodel <id or variant> - choose model for your Telegram jobs\n"
            "/split - show split mode\n"
            "/setsplit <off|on|auto|default|worker ids> - choose split mode\n"
            "/settings - show the worker and model that will be used",
        )
        return
    if command == "workers":
        await _command_workers(config, allowed_user, chat_id)
        return
    if command == "setworker":
        await _command_set_worker(config, allowed_user, chat_id, argument)
        return
    if command == "models":
        await _command_models(config, allowed_user, chat_id)
        return
    if command == "setmodel":
        await _command_set_model(config, allowed_user, chat_id, argument)
        return
    if command == "split":
        await _command_split(config, allowed_user, chat_id)
        return
    if command == "setsplit":
        await _command_set_split(config, allowed_user, chat_id, argument)
        return
    if command in {"settings", "current"}:
        await _command_settings(config, allowed_user, chat_id)
        return
    await send_telegram_message(config, chat_id, "Unknown command. Use /help for available commands.")


async def _telegram_workers(db: AsyncSession) -> list[TranscriptionWorker]:
    result = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.accepted.is_(True),
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    return sorted(result.scalars().all(), key=lambda worker: _worker_label(worker).lower())


async def _telegram_models(db: AsyncSession) -> list[TranscriptionModel]:
    result = await db.execute(
        select(TranscriptionModel).where(
            TranscriptionModel.status == "installed",
            TranscriptionModel.is_deleted.is_(False),
        )
    )
    return sorted(result.scalars().all(), key=lambda model: model.display_name.lower())


async def _command_workers(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
) -> None:
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
    if not workers:
        await send_telegram_message(config, chat_id, "No accepted workers are available.")
        return

    now = datetime.now(timezone.utc)
    lines = ["Workers:"]
    for worker in workers:
        marker = " *" if allowed_user.preferred_worker_id == worker.id else ""
        state = _worker_state(worker, now)
        variants = sorted(_worker_variants(worker), key=str.lower)
        model_text = ", ".join(variants[:5]) if variants else "no models"
        if len(variants) > 5:
            model_text += f", +{len(variants) - 5} more"
        lines.append(f"{worker.id}. {_worker_label(worker)} - {state} - {model_text}{marker}")
    lines.append("Use /setworker <id or name>.")
    await send_telegram_message(config, chat_id, "\n".join(lines))


async def _save_allowed_user_preferences(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    *,
    preferred_worker_id: int | None | object = ...,
    preferred_model_id: int | None | object = ...,
    split_enabled: bool | None | object = ...,
    split_worker_ids: list[int] | object = ...,
) -> TelegramBotSettings:
    updated_users: list[TelegramAllowedUser] = []
    for item in config.allowed_users:
        if item.telegram_user_id != allowed_user.telegram_user_id:
            updated_users.append(item)
            continue
        values = item.model_dump()
        if preferred_worker_id is not ...:
            values["preferred_worker_id"] = preferred_worker_id
        if preferred_model_id is not ...:
            values["preferred_model_id"] = preferred_model_id
        if split_enabled is not ...:
            values["split_enabled"] = split_enabled
        if split_worker_ids is not ...:
            values["split_worker_ids"] = split_worker_ids
        updated_users.append(TelegramAllowedUser.model_validate(values))

    async with async_session_factory() as db:
        return await update_telegram_bot_settings(
            db,
            TelegramBotSettingsUpdate(allowed_users=updated_users),
        )


async def _command_set_worker(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
    argument: str,
) -> None:
    if not argument:
        await send_telegram_message(config, chat_id, "Usage: /setworker <worker id or name>")
        return
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
        models = await _telegram_models(db)
    normalized = argument.strip().lower()
    worker = next(
        (
            item
            for item in workers
            if str(item.id) == normalized
            or item.name.lower() == normalized
            or (item.display_name or "").lower() == normalized
        ),
        None,
    )
    if worker is None:
        await send_telegram_message(config, chat_id, "Worker not found. Use /workers to see available workers.")
        return

    preferred_model_id = allowed_user.preferred_model_id
    selected_model = next((model for model in models if model.id == preferred_model_id), None)
    if selected_model and _catalog_install_variant(selected_model.variant) not in _worker_variants(worker):
        preferred_model_id = None

    await _save_allowed_user_preferences(
        config,
        allowed_user,
        preferred_worker_id=worker.id,
        preferred_model_id=preferred_model_id,
    )
    suffix = "\nYour previous model was cleared because this worker does not have it." if preferred_model_id is None and selected_model else ""
    await send_telegram_message(config, chat_id, f"Telegram worker set to {_worker_label(worker)}.{suffix}")


def _models_for_worker(
    models: list[TranscriptionModel],
    worker: TranscriptionWorker | None,
) -> list[TranscriptionModel]:
    if worker is None:
        return models
    variants = _worker_variants(worker)
    return [model for model in models if _catalog_install_variant(model.variant) in variants]


async def _command_models(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
) -> None:
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
        models = await _telegram_models(db)
    worker = next((item for item in workers if item.id == allowed_user.preferred_worker_id), None)
    available_models = _models_for_worker(models, worker)
    if not available_models:
        target = f" on {_worker_label(worker)}" if worker else ""
        await send_telegram_message(config, chat_id, f"No installed models are available{target}.")
        return

    title = f"Models for {_worker_label(worker)}:" if worker else "Models:"
    lines = [title]
    for model in available_models:
        marker = " *" if (allowed_user.preferred_model_id or config.default_model_id) == model.id else ""
        lines.append(f"{model.id}. {model.display_name} ({model.variant}){marker}")
    lines.append("Use /setmodel <id or variant>.")
    await send_telegram_message(config, chat_id, "\n".join(lines))


async def _command_set_model(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
    argument: str,
) -> None:
    if not argument:
        await send_telegram_message(config, chat_id, "Usage: /setmodel <model id or variant>")
        return
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
        models = await _telegram_models(db)
    worker = next((item for item in workers if item.id == allowed_user.preferred_worker_id), None)
    available_models = _models_for_worker(models, worker)
    normalized = argument.strip().lower()
    model = next(
        (
            item
            for item in available_models
            if str(item.id) == normalized
            or item.variant.lower() == normalized
            or item.display_name.lower() == normalized
        ),
        None,
    )
    if model is None:
        await send_telegram_message(config, chat_id, "Model not found for the selected worker. Use /models to see available models.")
        return
    await _save_allowed_user_preferences(config, allowed_user, preferred_model_id=model.id)
    await send_telegram_message(config, chat_id, f"Telegram model set to {model.display_name}.")


async def _command_settings(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
) -> None:
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
        models = await _telegram_models(db)

    model_id = allowed_user.preferred_model_id or config.default_model_id
    model = next((item for item in models if item.id == model_id), None)
    worker = next((item for item in workers if item.id == allowed_user.preferred_worker_id), None)
    model_source = "set for you" if allowed_user.preferred_model_id else "default"
    worker_source = "set for you" if allowed_user.preferred_worker_id else "automatic"
    split_enabled, split_worker_ids, split_source = _effective_split_config(config, allowed_user)

    lines = ["Telegram transcription settings:"]
    if model:
        install_variant = _catalog_install_variant(model.variant)
        lines.append(f"Model: {model.display_name} ({model.variant}) - {model_source}")
    elif model_id is None:
        install_variant = None
        lines.append("Model: not configured")
    else:
        install_variant = None
        lines.append("Model: configured model is no longer installed")

    now = datetime.now(timezone.utc)
    if worker:
        state = _worker_state(worker, now)
        has_model = bool(install_variant and install_variant in _worker_variants(worker))
        suffix = "has selected model" if has_model else "missing selected model"
        lines.append(f"Worker: {_worker_label(worker)} - {worker_source}, {state}, {suffix}")
    elif allowed_user.preferred_worker_id:
        lines.append("Worker: configured worker is no longer available")
    else:
        lines.append("Worker: automatic - first available capable worker will claim the job")

    if split_enabled:
        if split_worker_ids:
            split_names = []
            for worker_id in split_worker_ids:
                split_worker = next((item for item in workers if item.id == worker_id), None)
                split_names.append(_worker_label(split_worker) if split_worker else f"#{worker_id}")
            lines.append(f"Split: on ({split_source}) - {', '.join(split_names)}")
        else:
            lines.append(f"Split: on ({split_source}) - automatic capable workers")
    else:
        lines.append(f"Split: off ({split_source})")

    if install_variant:
        capable_workers = [
            item
            for item in workers
            if install_variant in _worker_variants(item)
        ]
        free_capable = [
            item
            for item in capable_workers
            if _worker_state(item, now) == "free"
        ]
        if capable_workers:
            lines.append("Capable workers:")
            for item in capable_workers:
                marker = " *" if worker and item.id == worker.id else ""
                lines.append(f"- {_worker_label(item)}: {_worker_state(item, now)}{marker}")
            if not worker:
                if free_capable:
                    names = ", ".join(_worker_label(item) for item in free_capable)
                    lines.append(f"If all are available, one of these can claim it: {names}.")
                else:
                    lines.append("No capable worker is free right now.")
        else:
            lines.append("No accepted worker currently reports this model installed.")

    lines.append("Use /workers, /setworker, /models, /setmodel, and /setsplit to change this.")
    await send_telegram_message(config, chat_id, "\n".join(lines))


def _effective_split_config(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
) -> tuple[bool, list[int], str]:
    if allowed_user.split_enabled is not None:
        return allowed_user.split_enabled, allowed_user.split_worker_ids, "set for you"
    return config.split_enabled, config.split_worker_ids, "default"


async def _command_split(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
) -> None:
    split_enabled, split_worker_ids, source = _effective_split_config(config, allowed_user)
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
    if split_enabled and split_worker_ids:
        names = []
        for worker_id in split_worker_ids:
            worker = next((item for item in workers if item.id == worker_id), None)
            names.append(_worker_label(worker) if worker else f"#{worker_id}")
        detail = f"selected workers: {', '.join(names)}"
    elif split_enabled:
        detail = "automatic capable workers"
    else:
        detail = "single worker"
    await send_telegram_message(
        config,
        chat_id,
        f"Split mode: {'on' if split_enabled else 'off'} ({source}) - {detail}\n"
        "Use /setsplit off, /setsplit on, /setsplit default, or /setsplit <worker ids>.",
    )


async def _command_set_split(
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    chat_id: str,
    argument: str,
) -> None:
    value = argument.strip().lower()
    if not value:
        await send_telegram_message(config, chat_id, "Usage: /setsplit <off|on|auto|default|worker ids>")
        return
    if value in {"default", "reset"}:
        await _save_allowed_user_preferences(config, allowed_user, split_enabled=None, split_worker_ids=[])
        await send_telegram_message(config, chat_id, "Telegram split mode reset to the admin default.")
        return
    if value in {"off", "false", "no", "0"}:
        await _save_allowed_user_preferences(config, allowed_user, split_enabled=False, split_worker_ids=[])
        await send_telegram_message(config, chat_id, "Telegram split mode disabled for your jobs.")
        return
    if value in {"on", "auto", "true", "yes", "1"}:
        await _save_allowed_user_preferences(config, allowed_user, split_enabled=True, split_worker_ids=[])
        await send_telegram_message(config, chat_id, "Telegram split mode enabled with automatic capable workers.")
        return

    worker_ids: list[int] = []
    for token in value.replace(",", " ").split():
        try:
            worker_ids.append(int(token))
        except ValueError:
            await send_telegram_message(config, chat_id, "Use worker ids, for example /setsplit 1 2.")
            return
    worker_ids = list(dict.fromkeys(worker_ids))
    if len(worker_ids) < 2:
        await send_telegram_message(config, chat_id, "Choose at least two workers for split mode, or use /setsplit on.")
        return
    async with async_session_factory() as db:
        workers = await _telegram_workers(db)
    found = {worker.id: worker for worker in workers}
    missing = [worker_id for worker_id in worker_ids if worker_id not in found]
    if missing:
        await send_telegram_message(config, chat_id, f"Unknown worker ids: {', '.join(map(str, missing))}.")
        return
    await _save_allowed_user_preferences(config, allowed_user, split_enabled=True, split_worker_ids=worker_ids)
    names = ", ".join(_worker_label(found[worker_id]) for worker_id in worker_ids)
    await send_telegram_message(config, chat_id, f"Telegram split mode enabled for: {names}.")


async def _handle_update(config: TelegramBotSettings, update: dict[str, Any]) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return
    chat_id = _chat_id(message)
    sender_id = _sender_id(message)
    if chat_id is None or sender_id is None:
        return

    allowed = {item.telegram_user_id: item for item in config.allowed_users}
    allowed_user = allowed.get(sender_id)
    if allowed_user is None:
        await send_telegram_message(config, chat_id, "This Telegram user is not allowed to submit audio.")
        return

    command = _parse_command(_message_text(message))
    if command is not None:
        await _handle_command(config, allowed_user, chat_id, command[0], command[1])
        return

    attachment = _attachment_from_message(message)
    if attachment is None:
        await send_telegram_message(
            config,
            chat_id,
            "Send an audio, voice message, or supported audio document.\n"
            "Commands: /workers, /setworker, /models, /setmodel, /settings",
        )
        return
    if not is_supported_audio(attachment.filename):
        await send_telegram_message(config, chat_id, "Unsupported audio file type.")
        return
    if attachment.file_size and attachment.file_size > settings.max_upload_mb * 1024 * 1024:
        await send_telegram_message(config, chat_id, f"Audio file is too large. Limit is {settings.max_upload_mb} MB.")
        return

    try:
        job = await _store_audio_and_create_job(
            config=config,
            app_user_id=allowed_user.app_user_id,
            telegram_user_id=sender_id,
            chat_id=chat_id,
            message_id=message.get("message_id"),
            attachment=attachment,
            allowed_user=allowed_user,
        )
    except ValueError as exc:
        await send_telegram_message(config, chat_id, str(exc))
        return

    await send_telegram_message(
        config,
        chat_id,
        f"Audio received: {attachment.filename}\nTranscription job #{job.id} queued.",
    )


async def _store_audio_and_create_job(
    *,
    config: TelegramBotSettings,
    app_user_id: int,
    telegram_user_id: int,
    chat_id: str,
    message_id: int | None,
    attachment: TelegramAttachment,
    allowed_user: TelegramAllowedUser,
) -> TranscriptionJob:
    async with async_session_factory() as db:
        split_enabled, split_worker_ids, _ = _effective_split_config(config, allowed_user)
        split_workers = await _load_split_workers(db, split_worker_ids) if split_enabled else []
        worker = None if split_enabled else await _load_preferred_worker(db, allowed_user)
        model = await _load_selected_model(db, config, allowed_user, worker)
        language = _normalize_job_language(model, config.default_language)
        stored_path, size = await _download_telegram_file(config, app_user_id, attachment)
        duration = await probe_duration_seconds(stored_path)
        audio = AudioFile(
            owner_user_id=app_user_id,
            project_id=None,
            original_filename=attachment.filename,
            display_name=attachment.filename,
            source="telegram",
            stored_path=str(stored_path),
            mime_type=attachment.mime_type or mimetypes.guess_type(attachment.filename)[0],
            size_bytes=size,
            duration_seconds=duration,
        )
        db.add(audio)
        await db.flush()
        job = TranscriptionJob(
            owner_user_id=app_user_id,
            audio_file_id=audio.id,
            model_id=model.id,
            language=language,
            status="queued",
            status_text="Waiting for worker",
            source="telegram",
            telegram_chat_id=chat_id,
            telegram_user_id=str(telegram_user_id),
            telegram_message_id=str(message_id) if message_id is not None else None,
            telegram_file_id=attachment.file_id,
            preferred_worker_id=None if split_enabled else (worker.id if worker else None),
            preferred_worker_name_snapshot=(
                f"Splitter: {', '.join(_worker_label(worker) for worker in split_workers)}"
                if split_workers
                else None if split_enabled else _worker_label(worker) if worker else None
            ),
            split_worker_ids_json=json.dumps([worker.id for worker in split_workers]) if split_workers else None,
            split_enabled=split_enabled,
            split_status="queued" if split_enabled else None,
        )
        db.add(job)
        await db.flush()
        if split_enabled:
            job.audio_file = audio
            job.model = model
            await create_split_chunks(db, job)
        await db.commit()
        await db.refresh(job)
        return job


async def _load_preferred_worker(
    db: AsyncSession,
    allowed_user: TelegramAllowedUser,
) -> TranscriptionWorker | None:
    if allowed_user.preferred_worker_id is None:
        return None
    result = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.id == allowed_user.preferred_worker_id,
            TranscriptionWorker.accepted.is_(True),
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise ValueError("Selected Telegram worker is no longer available. Use /workers and /setworker.")
    return worker


async def _load_split_workers(
    db: AsyncSession,
    worker_ids: list[int],
) -> list[TranscriptionWorker]:
    if not worker_ids:
        return []
    if len(worker_ids) < 2:
        raise ValueError("Telegram split mode needs at least two workers, or use automatic split mode.")
    result = await db.execute(
        select(TranscriptionWorker).where(
            TranscriptionWorker.id.in_(worker_ids),
            TranscriptionWorker.accepted.is_(True),
            TranscriptionWorker.is_deleted.is_not(True),
        )
    )
    found = {worker.id: worker for worker in result.scalars().all()}
    missing = [worker_id for worker_id in worker_ids if worker_id not in found]
    if missing:
        raise ValueError(f"Telegram split workers are no longer available: {', '.join(map(str, missing))}.")
    return [found[worker_id] for worker_id in worker_ids]


async def _load_selected_model(
    db: AsyncSession,
    config: TelegramBotSettings,
    allowed_user: TelegramAllowedUser,
    worker: TranscriptionWorker | None,
) -> TranscriptionModel:
    model_id = allowed_user.preferred_model_id or config.default_model_id
    if model_id is None:
        raise ValueError("Telegram transcription is not configured: default model is missing.")
    result = await db.execute(
        select(TranscriptionModel).where(
            TranscriptionModel.id == model_id,
            TranscriptionModel.status == "installed",
            TranscriptionModel.is_deleted.is_(False),
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        raise ValueError("Selected Telegram model is not installed. Use /models and /setmodel.")
    if worker and _catalog_install_variant(model.variant) not in _worker_variants(worker):
        raise ValueError(
            f"{_worker_label(worker)} does not have {model.display_name}. Use /models and /setmodel."
        )
    return model


def _normalize_job_language(model: TranscriptionModel, requested: str) -> str:
    language = requested or "auto"
    if model.language_mode == "english" and language == "auto":
        return "en"
    if model.language_mode == "russian" and language == "auto":
        return "ru"
    if model.language_mode == "english" and language not in {"auto", "en"}:
        raise ValueError("Telegram default language is incompatible with the default model.")
    if model.language_mode == "russian" and language not in {"auto", "ru"}:
        raise ValueError("Telegram default language is incompatible with the default model.")
    return language


async def _download_telegram_file(
    config: TelegramBotSettings,
    app_user_id: int,
    attachment: TelegramAttachment,
) -> tuple[Path, int]:
    response = await telegram_api_request(
        config,
        "GET",
        "getFile",
        params={"file_id": attachment.file_id},
    )
    if response.status_code != 200:
        raise ValueError("Could not fetch Telegram file metadata.")
    payload = response.json()
    if not payload.get("ok"):
        raise ValueError("Could not fetch Telegram file metadata.")
    file_path = payload.get("result", {}).get("file_path")
    if not file_path:
        raise ValueError("Telegram file path is missing.")

    suffix = Path(attachment.filename).suffix.lower()
    user_dir = settings.uploads_dir / str(app_user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored_path = user_dir / f"{uuid4().hex}{suffix}"
    url = f"https://api.telegram.org/file/bot{config.bot_token}/{file_path}"
    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        async with _telegram_client(config).stream("GET", url) as download:
            if download.status_code != 200:
                raise ValueError("Could not download Telegram file.")
            with stored_path.open("wb") as handle:
                async for chunk in download.aiter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"Audio file is too large. Limit is {settings.max_upload_mb} MB.")
                    handle.write(chunk)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    return stored_path, size


async def send_telegram_message(config: TelegramBotSettings, chat_id: str, text: str) -> bool:
    try:
        response = await telegram_api_request(
            config,
            "POST",
            "sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
    except TelegramTransportError as exc:
        logger.error("Telegram sendMessage failed: %s", exc)
        return False
    if response.status_code != 200:
        logger.error("Telegram sendMessage failed: %s", response.text)
        return False
    return True


async def notify_transcription_finished(job: TranscriptionJob) -> None:
    if job.source != "telegram" or not job.telegram_chat_id:
        return
    async with async_session_factory() as db:
        config = await get_telegram_bot_settings(db)
    if not config.bot_token:
        return

    error: str | None = None
    sent = False
    if job.status == "succeeded" and job.output_json_path:
        path = Path(job.output_json_path)
        if path.exists():
            try:
                with path.open("rb") as handle:
                    response = await telegram_api_request(
                        config,
                        "POST",
                        "sendDocument",
                        data={
                            "chat_id": job.telegram_chat_id,
                            "caption": f"Transcription job #{job.id} finished.",
                        },
                        files={
                            "document": (
                                f"transcription_{job.id}.json",
                                handle,
                                "application/json",
                            )
                        },
                    )
                if response.status_code == 200:
                    sent = True
                else:
                    error = response.text[:1000]
            except Exception as exc:
                error = str(exc)
        else:
            error = "Final transcription JSON file is missing."
    else:
        text = f"Transcription job #{job.id} {job.status}."
        if job.error_message:
            text += f"\n{job.error_message}"
        sent = await send_telegram_message(config, job.telegram_chat_id, text)
        if not sent:
            error = "Could not send Telegram status message."

    async with async_session_factory() as db:
        db_job = await db.get(TranscriptionJob, job.id)
        if db_job:
            db_job.telegram_result_sent_at = datetime.now(timezone.utc) if sent else None
            db_job.telegram_result_error = error
            await db.commit()
