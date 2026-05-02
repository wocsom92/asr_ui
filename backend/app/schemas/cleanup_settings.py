from __future__ import annotations

from pydantic import BaseModel, Field


class CleanupSettings(BaseModel):
    failed_cancelled_retention_days: int = Field(default=7, ge=1, le=3650)


class CleanupSettingsUpdate(BaseModel):
    failed_cancelled_retention_days: int = Field(ge=1, le=3650)


class CleanupSettingsOut(CleanupSettings):
    deleted_count_last_run: int = 0
