from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.files import AudioFileOut
from app.schemas.models import TranscriptionModelOut


class TranscriptionCreate(BaseModel):
    model_id: int
    language: str = "auto"

    model_config = {"protected_namespaces": ()}


class TranscriptionJobOut(BaseModel):
    id: int
    owner_user_id: int
    audio_file_id: int
    model_id: int
    language: str
    status: str
    status_text: Optional[str]
    error_message: Optional[str]
    transcript_text: Optional[str]
    output_txt_size_bytes: Optional[int] = None
    output_json_size_bytes: Optional[int] = None
    output_srt_size_bytes: Optional[int] = None
    output_vtt_size_bytes: Optional[int] = None
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    audio_file: Optional[AudioFileOut] = None
    model: Optional[TranscriptionModelOut] = None

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class TranscriptionSegmentOut(BaseModel):
    start: float
    end: float
    text: str
