from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AudioFileOut(BaseModel):
    id: int
    original_filename: str
    display_name: Optional[str]
    notes: Optional[str]
    mime_type: Optional[str]
    size_bytes: int
    duration_seconds: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class AudioFileUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=10000)
