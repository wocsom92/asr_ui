from pathlib import Path
from typing import Optional
import socket

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
    telegram_proxy_url: Optional[str] = None
    asr_worker_enabled: bool = True
    asr_worker_name: Optional[str] = None
    asr_worker_token: Optional[str] = None
    asr_server_url: str = "http://127.0.0.1:8000"
    asr_worker_concurrency: int = 1
    asr_worker_auto_install_models: bool = True
    asr_worker_heartbeat_seconds: float = 5.0
    asr_worker_offline_seconds: float = 20.0
    asr_split_min_chunk_seconds: int = 300
    asr_split_overlap_seconds: int = 5
    asr_split_max_chunks: int = 8
    gigaam_chunk_max_seconds: float = 24.0
    gigaam_chunk_target_seconds: float = 22.0
    gigaam_chunk_overlap_seconds: float = 1.0
    gigaam_vad_enabled: bool = True
    gigaam_vad_mode: int = 2
    gigaam_vad_merge_silence_ms: int = 500
    gigaam_vad_pad_ms: int = 200
    gigaam_torch_threads: Optional[int] = None
    gigaam_torch_interop_threads: Optional[int] = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def default_worker_name() -> str:
    return settings.asr_worker_name or socket.gethostname() or "worker"
