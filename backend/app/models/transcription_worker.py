from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptionWorker(Base):
    __tablename__ = "transcription_workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="offline", index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    current_job_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_job_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_job_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_job_count: Mapped[int] = mapped_column(Integer, default=0)
    total_runtime_seconds: Mapped[float] = mapped_column(default=0.0)
    total_audio_seconds: Mapped[float] = mapped_column(default=0.0)
    model_speed_stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_inventory_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    install_status_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_installs_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_uninstalls_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_install_models: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(  # noqa: F821
        back_populates="worker",
        foreign_keys="TranscriptionJob.worker_id",
    )
    transcription_chunks: Mapped[list["TranscriptionJobChunk"]] = relationship(  # noqa: F821
        back_populates="worker"
    )
