from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.summarization_settings import SummarizationSettings, SummarizationSettingsUpdate

SETTINGS_KEY = "summarization_settings"


def default_summarization_settings() -> SummarizationSettings:
    return SummarizationSettings(ollama_base_url=settings.summarization_ollama_base_url)


async def get_summarization_settings(db: AsyncSession) -> SummarizationSettings:
    defaults = default_summarization_settings()
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
    merged = defaults.model_dump()
    if isinstance(payload, dict):
        merged.update(payload)
    return SummarizationSettings.model_validate(merged)


async def update_summarization_settings(
    db: AsyncSession,
    body: SummarizationSettingsUpdate,
) -> SummarizationSettings:
    updated = SummarizationSettings.model_validate(body.model_dump())
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": SETTINGS_KEY, "value": json.dumps(updated.model_dump(), ensure_ascii=False)},
    )
    await db.commit()
    return updated
