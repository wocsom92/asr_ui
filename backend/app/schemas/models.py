from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ModelCatalogItem(BaseModel):
    provider: str
    variant: str
    display_name: str
    language_mode: str
    disk_hint: str
    ram_hint: str
    download_url: str
    model_variant: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class ModelInstallRequest(BaseModel):
    variant: str


class TranscriptionModelOut(BaseModel):
    id: int
    provider: str
    variant: str
    display_name: str
    language_mode: str
    download_url: Optional[str]
    status: str
    size_bytes: Optional[int]
    downloaded_bytes: int
    total_bytes: Optional[int]
    status_text: Optional[str]
    error_message: Optional[str]
    installed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptionModelStatsOut(BaseModel):
    model_id: int
    worker_id: Optional[int] = None
    worker_name: Optional[str] = None
    completed_job_count: int
    total_audio_seconds: float
    total_runtime_seconds: float
    runtime_per_audio_hour_seconds: float
    median_runtime_per_audio_hour_seconds: Optional[float]
    last_completed_at: Optional[datetime]

    model_config = {"protected_namespaces": ()}
