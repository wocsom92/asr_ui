from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.cleanup_settings import CleanupSettings, CleanupSettingsUpdate

SETTINGS_KEY = "cleanup_settings"


def default_cleanup_settings() -> CleanupSettings:
    return CleanupSettings()


async def get_cleanup_settings(db: AsyncSession) -> CleanupSettings:
    defaults = default_cleanup_settings()
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
    return CleanupSettings.model_validate(merged)


async def update_cleanup_settings(
    db: AsyncSession,
    body: CleanupSettingsUpdate,
) -> CleanupSettings:
    updated = CleanupSettings.model_validate(body.model_dump())
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": SETTINGS_KEY, "value": json.dumps(updated.model_dump(), ensure_ascii=False)},
    )
    await db.commit()
    return updated
