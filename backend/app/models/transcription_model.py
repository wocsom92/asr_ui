from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptionModel(Base):
    __tablename__ = "transcription_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="whisper.cpp", index=True)
    variant: Mapped[str] = mapped_column(String(100), index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    language_mode: Mapped[str] = mapped_column(String(20), default="multilingual")
    path: Mapped[str] = mapped_column(String(1000))
    download_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="installing", index=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    installed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(  # noqa: F821
        back_populates="model"
    )
