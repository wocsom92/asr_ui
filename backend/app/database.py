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
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_settings "
                "(key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
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
            ("partial_transcript_text", "TEXT"),
            ("partial_transcript_json", "TEXT"),
            ("partial_updated_at", "DATETIME"),
            ("source", "VARCHAR(50)"),
            ("telegram_chat_id", "VARCHAR(100)"),
            ("telegram_user_id", "VARCHAR(100)"),
            ("telegram_message_id", "VARCHAR(100)"),
            ("telegram_file_id", "VARCHAR(255)"),
            ("telegram_result_sent_at", "DATETIME"),
            ("telegram_result_error", "TEXT"),
            ("worker_id", "INTEGER"),
            ("worker_name_snapshot", "VARCHAR(120)"),
            ("preferred_worker_id", "INTEGER"),
            ("preferred_worker_name_snapshot", "VARCHAR(120)"),
            ("split_worker_ids_json", "TEXT"),
            ("claimed_at", "DATETIME"),
            ("worker_heartbeat_at", "DATETIME"),
            ("cancel_requested_at", "DATETIME"),
            ("split_enabled", "BOOLEAN DEFAULT 0"),
            ("split_status", "VARCHAR(30)"),
        ):
            try:
                await conn.execute(
                    text(f"ALTER TABLE transcription_jobs ADD COLUMN {column} {col_type}")
                )
            except Exception:
                pass
        try:
            await conn.execute(
                text(
                    "UPDATE transcription_jobs "
                    "SET split_enabled = 0 "
                    "WHERE split_enabled IS NULL"
                )
            )
        except Exception:
            pass
        for column, col_type in (
            ("display_name", "VARCHAR(160)"),
            ("accepted", "BOOLEAN DEFAULT 1"),
            ("is_deleted", "BOOLEAN DEFAULT 0"),
            ("status", "VARCHAR(30) DEFAULT 'offline'"),
            ("last_heartbeat_at", "DATETIME"),
            ("current_job_count", "INTEGER DEFAULT 0"),
            ("completed_job_count", "INTEGER DEFAULT 0"),
            ("failed_job_count", "INTEGER DEFAULT 0"),
            ("cancelled_job_count", "INTEGER DEFAULT 0"),
            ("total_runtime_seconds", "FLOAT DEFAULT 0"),
            ("total_audio_seconds", "FLOAT DEFAULT 0"),
            ("model_speed_stats_json", "TEXT"),
            ("model_inventory_json", "TEXT"),
            ("install_status_json", "TEXT"),
            ("requested_installs_json", "TEXT"),
            ("requested_uninstalls_json", "TEXT"),
            ("last_error", "TEXT"),
            ("auto_install_models", "BOOLEAN DEFAULT 1"),
            ("updated_at", "DATETIME"),
        ):
            try:
                await conn.execute(
                    text(f"ALTER TABLE transcription_workers ADD COLUMN {column} {col_type}")
                )
            except Exception:
                pass
        try:
            await conn.execute(
                text(
                    "UPDATE transcription_workers "
                    "SET accepted = 1 "
                    "WHERE accepted IS NULL"
                )
            )
        except Exception:
            pass
        try:
            await conn.execute(
                text(
                    "UPDATE transcription_workers "
                    "SET is_deleted = 0 "
                    "WHERE is_deleted IS NULL"
                )
            )
        except Exception:
            pass
        for column, col_type in (
            ("display_name", "VARCHAR(255)"),
            ("notes", "TEXT"),
            ("source", "VARCHAR(50)"),
            ("project_id", "INTEGER"),
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
        try:
            await conn.execute(
                text(
                    "UPDATE audio_files "
                    "SET source = 'telegram' "
                    "WHERE EXISTS ("
                    "  SELECT 1 FROM transcription_jobs "
                    "  WHERE transcription_jobs.audio_file_id = audio_files.id "
                    "  AND transcription_jobs.source = 'telegram'"
                    ")"
                )
            )
        except Exception:
            pass
        try:
            await conn.execute(
                text(
                    "UPDATE audio_files "
                    "SET source = 'web' "
                    "WHERE source IS NULL OR TRIM(source) = ''"
                )
            )
        except Exception:
            pass
