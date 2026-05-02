from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.whisper_settings import WhisperCliSettings, WhisperCliSettingsUpdate

_SETTING_KEY = "whisper_cli_settings"


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def default_whisper_cli_settings() -> WhisperCliSettings:
    return WhisperCliSettings(
        whisper_threads=settings.whisper_threads,
        whisper_max_context=settings.whisper_max_context,
        whisper_use_gpu=settings.whisper_use_gpu,
        whisper_flash_attn=settings.whisper_flash_attn,
        whisper_suppress_non_speech=settings.whisper_suppress_non_speech,
        whisper_suppress_regex=_clean_optional_text(settings.whisper_suppress_regex),
        transcript_filter_regex=_clean_optional_text(settings.transcript_filter_regex),
    )


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ("whisper_suppress_regex", "transcript_filter_regex"):
        if key in normalized:
            normalized[key] = _clean_optional_text(normalized[key])
    return normalized


async def get_whisper_cli_settings(db: AsyncSession) -> WhisperCliSettings:
    defaults = default_whisper_cli_settings()
    result = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :key"),
        {"key": _SETTING_KEY},
    )
    raw = result.scalar_one_or_none()
    if not raw:
        return defaults
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    return defaults.model_copy(update=_normalize_payload(payload))


async def update_whisper_cli_settings(
    db: AsyncSession,
    body: WhisperCliSettingsUpdate,
) -> WhisperCliSettings:
    current = await get_whisper_cli_settings(db)
    update = _normalize_payload(body.model_dump(exclude_unset=True))
    updated = current.model_copy(update=update)
    payload = json.dumps(updated.model_dump(), ensure_ascii=False)
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": _SETTING_KEY, "value": payload},
    )
    await db.commit()
    return updated


async def reset_whisper_cli_settings(db: AsyncSession) -> WhisperCliSettings:
    await db.execute(text("DELETE FROM app_settings WHERE key = :key"), {"key": _SETTING_KEY})
    await db.commit()
    return default_whisper_cli_settings()


def whisper_cli_preview(config: WhisperCliSettings) -> list[str]:
    args = [
        settings.whisper_cpp_bin,
        "-m",
        "<model>",
        "-f",
        "<input.wav>",
        "-t",
        str(config.whisper_threads),
        "-mc",
        str(config.whisper_max_context),
        "-otxt",
        "-osrt",
        "-ovtt",
        "-oj",
        "-of",
        "<output/transcript>",
    ]
    if not config.whisper_use_gpu:
        args.append("-ng")
    if not config.whisper_flash_attn:
        args.append("-nfa")
    if config.whisper_suppress_non_speech:
        args.append("-sns")
    if config.whisper_suppress_regex:
        args.extend(["--suppress-regex", config.whisper_suppress_regex])
    args.extend(["-l", "<job language>", "-pp"])
    return args
