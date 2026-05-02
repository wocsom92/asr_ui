from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class WhisperCliSettings(BaseModel):
    whisper_threads: int = Field(ge=1, le=64)
    whisper_max_context: int = Field(ge=-1, le=8192)
    whisper_use_gpu: bool
    whisper_flash_attn: bool
    whisper_suppress_non_speech: bool
    whisper_suppress_regex: Optional[str] = Field(default=None, max_length=1000)
    transcript_filter_regex: Optional[str] = Field(default=None, max_length=1000)


class WhisperCliSettingsUpdate(BaseModel):
    whisper_threads: Optional[int] = Field(default=None, ge=1, le=64)
    whisper_max_context: Optional[int] = Field(default=None, ge=-1, le=8192)
    whisper_use_gpu: Optional[bool] = None
    whisper_flash_attn: Optional[bool] = None
    whisper_suppress_non_speech: Optional[bool] = None
    whisper_suppress_regex: Optional[str] = Field(default=None, max_length=1000)
    transcript_filter_regex: Optional[str] = Field(default=None, max_length=1000)


class WhisperCliSettingsOut(WhisperCliSettings):
    defaults: WhisperCliSettings
    cli_preview: list[str]
