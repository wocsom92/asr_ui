from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="user")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    audio_files: Mapped[list["AudioFile"]] = relationship(  # noqa: F821
        back_populates="owner", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        back_populates="owner", cascade="all, delete-orphan"
    )
    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(  # noqa: F821
        back_populates="owner", cascade="all, delete-orphan"
    )
