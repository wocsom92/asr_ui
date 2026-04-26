from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    owner: Mapped["User"] = relationship(back_populates="transcription_jobs")  # noqa: F821
    audio_file: Mapped["AudioFile"] = relationship(back_populates="transcription_jobs")  # noqa: F821
    model: Mapped["TranscriptionModel"] = relationship(back_populates="transcription_jobs")  # noqa: F821

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
