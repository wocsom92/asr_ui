from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transcription_model import TranscriptionModel
from app.models.user import User
from app.config import settings
from app.schemas.telegram_settings import (
    TelegramAllowedUser,
    TelegramBotSettings,
    TelegramBotSettingsUpdate,
)

SETTINGS_KEY = "telegram_bot_settings"
OFFSET_KEY = "telegram_bot_update_offset"


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_allowed_users(raw: Any) -> list[TelegramAllowedUser]:
    if not isinstance(raw, list):
        return []
    users: list[TelegramAllowedUser] = []
    seen: set[int] = set()
    for item in raw:
        try:
            allowed = TelegramAllowedUser.model_validate(item)
        except Exception:
            continue
        if allowed.telegram_user_id in seen:
            continue
        allowed.split_worker_ids = _normalize_worker_ids(allowed.split_worker_ids)
        seen.add(allowed.telegram_user_id)
        users.append(allowed)
    return users


def _normalize_worker_ids(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    clean: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            worker_id = int(item)
        except (TypeError, ValueError):
            continue
        if worker_id <= 0 or worker_id in seen:
            continue
        seen.add(worker_id)
        clean.append(worker_id)
    return clean


def default_telegram_bot_settings() -> TelegramBotSettings:
    return TelegramBotSettings(proxy_url=_clean_optional_text(settings.telegram_proxy_url))


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "bot_token" in normalized:
        normalized["bot_token"] = _clean_optional_text(normalized["bot_token"])
    if "proxy_url" in normalized:
        normalized["proxy_url"] = _clean_optional_text(normalized["proxy_url"])
    if "default_language" in normalized:
        normalized["default_language"] = (normalized["default_language"] or "auto").strip() or "auto"
    if "split_worker_ids" in normalized:
        normalized["split_worker_ids"] = _normalize_worker_ids(normalized["split_worker_ids"])
    if "allowed_users" in normalized:
        normalized["allowed_users"] = [
            item.model_dump() for item in _normalize_allowed_users(normalized["allowed_users"])
        ]
    return normalized


def token_preview(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


async def get_telegram_bot_settings(db: AsyncSession) -> TelegramBotSettings:
    defaults = default_telegram_bot_settings()
    result = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :key"),
        {"key": SETTINGS_KEY},
    )
    raw = result.scalar_one_or_none()
    if not raw:
        return defaults
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    normalized = _normalize_payload(payload)
    merged = defaults.model_dump()
    for key, value in normalized.items():
        if key == "proxy_url" and value is None and defaults.proxy_url:
            continue
        merged[key] = value
    return TelegramBotSettings.model_validate(merged)


async def get_telegram_update_offset(db: AsyncSession) -> int | None:
    result = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :key"),
        {"key": OFFSET_KEY},
    )
    raw = result.scalar_one_or_none()
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def set_telegram_update_offset(db: AsyncSession, offset: int) -> None:
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": OFFSET_KEY, "value": str(offset)},
    )
    await db.commit()


async def _validate_settings(db: AsyncSession, config: TelegramBotSettings) -> None:
    if config.default_language not in {"auto", "en", "ru"}:
        raise HTTPException(status_code=400, detail="Telegram default language must be auto, en, or ru")

    if config.split_enabled and config.split_worker_ids and len(config.split_worker_ids) < 2:
        raise HTTPException(status_code=400, detail="Telegram split mode needs at least two default split workers")
    for item in config.allowed_users:
        if item.split_enabled and item.split_worker_ids and len(item.split_worker_ids) < 2:
            raise HTTPException(status_code=400, detail="Allowed Telegram user split mode needs at least two workers")

    if config.default_model_id is not None:
        result = await db.execute(
            select(TranscriptionModel).where(
                TranscriptionModel.id == config.default_model_id,
                TranscriptionModel.status == "installed",
                TranscriptionModel.is_deleted.is_(False),
            )
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=400, detail="Telegram default model must be installed")
        if model.language_mode == "english" and config.default_language not in {"auto", "en"}:
            raise HTTPException(status_code=400, detail="English-only model only supports English")
        if model.language_mode == "russian" and config.default_language not in {"auto", "ru"}:
            raise HTTPException(status_code=400, detail="Russian model only supports Russian")

    worker_ids = {item.preferred_worker_id for item in config.allowed_users if item.preferred_worker_id is not None}
    worker_ids.update(config.split_worker_ids)
    for item in config.allowed_users:
        worker_ids.update(item.split_worker_ids)
    if worker_ids:
        from app.models.transcription_worker import TranscriptionWorker

        result = await db.execute(
            select(TranscriptionWorker.id).where(
                TranscriptionWorker.id.in_(worker_ids),
                TranscriptionWorker.accepted.is_(True),
                TranscriptionWorker.is_deleted.is_not(True),
            )
        )
        existing_workers = set(result.scalars().all())
        if worker_ids - existing_workers:
            raise HTTPException(status_code=400, detail="Allowed Telegram mapping contains unknown worker")

    if config.allowed_users:
        user_ids = {item.app_user_id for item in config.allowed_users}
        result = await db.execute(select(User.id).where(User.id.in_(user_ids)))
        existing = set(result.scalars().all())
        missing = user_ids - existing
        if missing:
            raise HTTPException(status_code=400, detail="Allowed Telegram mapping contains unknown ASR user")

        model_ids = {item.preferred_model_id for item in config.allowed_users if item.preferred_model_id is not None}
        if model_ids:
            result = await db.execute(
                select(TranscriptionModel.id).where(
                    TranscriptionModel.id.in_(model_ids),
                    TranscriptionModel.status == "installed",
                    TranscriptionModel.is_deleted.is_(False),
                )
            )
            existing_models = set(result.scalars().all())
            if model_ids - existing_models:
                raise HTTPException(status_code=400, detail="Allowed Telegram mapping contains unknown model")

    if config.enabled:
        if not config.bot_token:
            raise HTTPException(status_code=400, detail="Telegram bot token is required when enabled")
        if config.default_model_id is None:
            raise HTTPException(status_code=400, detail="Telegram default model is required when enabled")
        if not config.allowed_users:
            raise HTTPException(status_code=400, detail="At least one allowed Telegram user is required when enabled")


async def update_telegram_bot_settings(
    db: AsyncSession,
    body: TelegramBotSettingsUpdate,
) -> TelegramBotSettings:
    current = await get_telegram_bot_settings(db)
    update = _normalize_payload(body.model_dump(exclude_unset=True))
    if "bot_token" in update and update["bot_token"] is None:
        update["bot_token"] = None
    elif "bot_token" in update and update["bot_token"] == "":
        update["bot_token"] = None
    merged = current.model_dump()
    merged.update(update)
    updated = TelegramBotSettings.model_validate(merged)
    updated.allowed_users = _normalize_allowed_users(updated.allowed_users)
    await _validate_settings(db, updated)
    payload = json.dumps(updated.model_dump(), ensure_ascii=False)
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": SETTINGS_KEY, "value": payload},
    )
    await db.commit()
    return updated
