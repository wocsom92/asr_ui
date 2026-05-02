from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptionJobChunk(Base):
    __tablename__ = "transcription_job_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_job_id: Mapped[int] = mapped_column(ForeignKey("transcription_jobs.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    overlap_start_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    overlap_end_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    status_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transcription_workers.id"), nullable=True, index=True)
    worker_name_snapshot: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_srt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_vtt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    parent_job: Mapped["TranscriptionJob"] = relationship(back_populates="chunks")  # noqa: F821
    worker: Mapped[Optional["TranscriptionWorker"]] = relationship(back_populates="transcription_chunks")  # noqa: F821
