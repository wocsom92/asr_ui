from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkerModelState(BaseModel):
    variant: str
    status: str
    path: Optional[str] = None
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    error_message: Optional[str] = None


class WorkerModelSpeedStat(BaseModel):
    variant: str
    completed_count: int = 0
    total_runtime_seconds: float = 0.0
    total_audio_seconds: float = 0.0
    runtime_per_audio_hour_seconds: Optional[float] = None


class WorkerHeartbeatIn(BaseModel):
    name: str
    status: str = "idle"
    current_job_count: int = 0
    models: list[WorkerModelState] = []
    installs: list[WorkerModelState] = []
    auto_install_models: bool = True
    last_error: Optional[str] = None


class WorkerOut(BaseModel):
    id: int
    name: str
    display_name: Optional[str] = None
    accepted: bool = False
    is_deleted: bool = False
    status: str
    online: bool = False
    last_heartbeat_at: Optional[datetime]
    current_job_count: int
    completed_job_count: int
    failed_job_count: int
    cancelled_job_count: int
    total_runtime_seconds: float
    total_audio_seconds: float
    model_speed_stats: list[WorkerModelSpeedStat] = []
    models: list[WorkerModelState] = []
    installs: list[WorkerModelState] = []
    requested_installs: list[str] = []
    requested_uninstalls: list[str] = []
    last_error: Optional[str]
    auto_install_models: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class WorkerUpdateIn(BaseModel):
    display_name: Optional[str] = None
    accepted: Optional[bool] = None


class WorkerInstallRequestIn(BaseModel):
    variant: str


class WorkerUninstallRequestIn(BaseModel):
    variant: str


class WorkerClaimIn(BaseModel):
    name: str
    models: list[WorkerModelState] = []
    auto_install_models: bool = True


class WorkerClaimOut(BaseModel):
    kind: Optional[str] = None
    job_id: Optional[int] = None
    chunk_id: Optional[int] = None
    audio_file_id: Optional[int] = None
    model_id: Optional[int] = None
    model_variant: Optional[str] = None
    model_download_url: Optional[str] = None
    language: Optional[str] = None
    owner_user_id: Optional[int] = None
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    cancel_requested: bool = False

    model_config = {"protected_namespaces": ()}


class WorkerProgressIn(BaseModel):
    status_text: Optional[str] = None
    partial_transcript_text: Optional[str] = None
    partial_transcript_json: Optional[str] = None


class WorkerFinishIn(BaseModel):
    status: str
    transcript_text: Optional[str] = None
    output_json: Optional[str] = None
    output_srt: Optional[str] = None
    output_vtt: Optional[str] = None
    error_message: Optional[str] = None
