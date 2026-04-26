import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session_factory() as session:
        yield session


async def init_db():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)

    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for column, col_type in (
            ("download_url", "VARCHAR(1000)"),
            ("downloaded_bytes", "INTEGER DEFAULT 0"),
            ("total_bytes", "INTEGER"),
            ("status_text", "VARCHAR(255)"),
            ("is_deleted", "BOOLEAN DEFAULT 0"),
        ):
            try:
                await conn.execute(
                    text(
                        f"ALTER TABLE transcription_models "
                        f"ADD COLUMN {column} {col_type}"
                    )
                )
            except Exception:
                pass
        try:
            await conn.execute(
                text(
                    "UPDATE transcription_models "
                    "SET is_deleted = 0 "
                    "WHERE is_deleted IS NULL"
                )
            )
        except Exception:
            pass
        for column, col_type in (
            ("display_name", "VARCHAR(255)"),
            ("notes", "TEXT"),
        ):
            try:
                await conn.execute(
                    text(f"ALTER TABLE audio_files ADD COLUMN {column} {col_type}")
                )
            except Exception:
                pass
        try:
            await conn.execute(
                text(
                    "UPDATE audio_files "
                    "SET display_name = original_filename "
                    "WHERE display_name IS NULL OR TRIM(display_name) = ''"
                )
            )
        except Exception:
            pass
