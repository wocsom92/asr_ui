from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    audio_file_id: Mapped[int] = mapped_column(ForeignKey("audio_files.id"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("transcription_models.id"))
    language: Mapped[str] = mapped_column(String(20), default="auto")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    status_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_txt_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    output_json_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    output_srt_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    output_vtt_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    partial_transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partial_transcript_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partial_updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_status: Mapped[str] = mapped_column(String(20), default="idle", index=True)
    summary_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    summary_queued_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    summary_started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    summary_finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    summary_updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telegram_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_result_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    telegram_result_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_summary_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_summary_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    telegram_summary_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transcription_workers.id"), nullable=True, index=True)
    worker_name_snapshot: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    preferred_worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transcription_workers.id"), nullable=True, index=True)
    preferred_worker_name_snapshot: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    split_worker_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    worker_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    split_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    split_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    owner: Mapped["User"] = relationship(back_populates="transcription_jobs")  # noqa: F821
    audio_file: Mapped["AudioFile"] = relationship(back_populates="transcription_jobs")  # noqa: F821
    model: Mapped["TranscriptionModel"] = relationship(back_populates="transcription_jobs")  # noqa: F821
    worker: Mapped[Optional["TranscriptionWorker"]] = relationship(  # noqa: F821
        back_populates="transcription_jobs",
        foreign_keys=[worker_id],
    )
    chunks: Mapped[list["TranscriptionJobChunk"]] = relationship(  # noqa: F821
        back_populates="parent_job", cascade="all, delete-orphan"
    )

    @staticmethod
    def _path_size(path_value: Optional[str]) -> Optional[int]:
        if not path_value:
            return None
        path = Path(path_value)
        return path.stat().st_size if path.exists() else None

    @property
    def output_txt_size_bytes(self) -> Optional[int]:
        return self._path_size(self.output_txt_path)

    @property
    def output_json_size_bytes(self) -> Optional[int]:
        return self._path_size(self.output_json_path)

    @property
    def output_srt_size_bytes(self) -> Optional[int]:
        return self._path_size(self.output_srt_path)

    @property
    def output_vtt_size_bytes(self) -> Optional[int]:
        return self._path_size(self.output_vtt_path)

    @property
    def split_chunk_count(self) -> int:
        return len(self.chunks or [])

    @property
    def split_chunks_completed(self) -> int:
        return sum(1 for chunk in self.chunks or [] if chunk.status == "succeeded")

    @property
    def split_chunks_running(self) -> int:
        return sum(1 for chunk in self.chunks or [] if chunk.status == "running")

    @property
    def split_chunks_queued(self) -> int:
        return sum(1 for chunk in self.chunks or [] if chunk.status == "queued")

    @property
    def split_chunks_failed(self) -> int:
        return sum(1 for chunk in self.chunks or [] if chunk.status == "failed")

    @property
    def running_worker_names(self) -> list[str]:
        names: set[str] = set()
        if self.status == "running" and self.worker_name_snapshot:
            names.add(self.worker_name_snapshot)
        for chunk in self.chunks or []:
            if chunk.status == "running" and chunk.worker_name_snapshot:
                names.add(chunk.worker_name_snapshot)
        return sorted(names, key=str.lower)

    @property
    def split_chunks(self) -> list["TranscriptionJobChunk"]:  # noqa: F821
        return sorted(self.chunks or [], key=lambda chunk: chunk.index)

    @property
    def split_worker_ids(self) -> list[int]:
        if not self.split_worker_ids_json:
            return []
        try:
            raw = json.loads(self.split_worker_ids_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        ids: list[int] = []
        for value in raw:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return ids
