from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:////data/asr_ui.db"
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8824"]

    data_dir: Path = Path("/data")
    uploads_dir: Path = Path("/data/uploads")
    outputs_dir: Path = Path("/data/transcripts")
    models_dir: Path = Path("/models")
    max_upload_mb: int = 2048

    whisper_cpp_bin: str = "/opt/whisper.cpp/build/bin/whisper-cli"
    whisper_threads: int = 4
    whisper_max_context: int = 0
    # whisper.cpp defaults to GPU + flash attention; both can crash or mis-allocate in
    # common Docker/CPU-only setups (e.g. std::length_error on model init). Opt in explicitly.
    whisper_use_gpu: bool = False
    whisper_flash_attn: bool = False
    whisper_suppress_non_speech: bool = True
    whisper_suppress_regex: Optional[str] = None
    transcript_filter_regex: Optional[str] = None
    transcription_poll_seconds: float = 2.0

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
