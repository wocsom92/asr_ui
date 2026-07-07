from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.files import AudioFileOut
from app.schemas.models import TranscriptionModelOut


class TranscriptionCreate(BaseModel):
    model_id: int
    language: str = "auto"
    split_enabled: bool = False
    preferred_worker_id: Optional[int] = None
    split_worker_ids: list[int] = []

    model_config = {"protected_namespaces": ()}


class TranscriptionJobChunkOut(BaseModel):
    id: int
    index: int
    start_seconds: float
    end_seconds: float
    overlap_start_seconds: float
    overlap_end_seconds: float
    status: str
    status_text: Optional[str] = None
    error_message: Optional[str] = None
    worker_id: Optional[int] = None
    worker_name_snapshot: Optional[str] = None
    claimed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TranscriptionJobBaseOut(BaseModel):
    """Shared job fields for list and detail responses."""

    id: int
    owner_user_id: int
    audio_file_id: int
    model_id: int
    language: str
    status: str
    status_text: Optional[str]
    error_message: Optional[str]
    output_txt_size_bytes: Optional[int] = None
    output_json_size_bytes: Optional[int] = None
    output_srt_size_bytes: Optional[int] = None
    output_vtt_size_bytes: Optional[int] = None
    partial_transcript_text: Optional[str] = None
    partial_updated_at: Optional[datetime] = None
    summary_status: str = "idle"
    summary_error: Optional[str] = None
    summary_model: Optional[str] = None
    summary_queued_at: Optional[datetime] = None
    summary_started_at: Optional[datetime] = None
    summary_finished_at: Optional[datetime] = None
    summary_updated_at: Optional[datetime] = None
    source: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_user_id: Optional[str] = None
    telegram_message_id: Optional[str] = None
    telegram_file_id: Optional[str] = None
    telegram_result_sent_at: Optional[datetime] = None
    telegram_result_error: Optional[str] = None
    telegram_summary_requested: bool = False
    telegram_summary_sent_at: Optional[datetime] = None
    telegram_summary_error: Optional[str] = None
    worker_id: Optional[int] = None
    worker_name_snapshot: Optional[str] = None
    preferred_worker_id: Optional[int] = None
    preferred_worker_name_snapshot: Optional[str] = None
    split_worker_ids: list[int] = []
    claimed_at: Optional[datetime] = None
    worker_heartbeat_at: Optional[datetime] = None
    cancel_requested_at: Optional[datetime] = None
    split_enabled: bool = False
    split_status: Optional[str] = None
    split_chunk_count: int = 0
    split_chunks_completed: int = 0
    split_chunks_running: int = 0
    split_chunks_queued: int = 0
    split_chunks_failed: int = 0
    running_worker_names: list[str] = []
    split_chunks: list[TranscriptionJobChunkOut] = []
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    audio_file: Optional[AudioFileOut] = None
    model: Optional[TranscriptionModelOut] = None

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class TranscriptionJobListOut(TranscriptionJobBaseOut):
    """Slim list payload: omits large TEXT blobs that are deferred in list queries.

    Must stay in sync with ``_LIST_DEFERRED_FIELDS`` in the transcriptions router.
    Using a separate schema prevents Pydantic from lazy-loading deferred columns
    during response validation (which causes MissingGreenlet 500 errors).
    """


class TranscriptionJobOut(TranscriptionJobBaseOut):
    transcript_text: Optional[str]
    partial_transcript_json: Optional[str] = None
    summary_text: Optional[str] = None


class TranscriptionSegmentOut(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class SegmentEdit(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class SegmentsUpdate(BaseModel):
    segments: list[SegmentEdit] = []


class BulkIdsRequest(BaseModel):
    ids: list[int] = []


class TranscriptionStatsOut(BaseModel):
    total: int = 0
    finished: int = 0
    active_transcriptions: int = 0
    active_summaries: int = 0
    failed_summaries: int = 0
    completed_summaries: int = 0
    transcript_storage_bytes: int = 0
    summary_word_count: int = 0
    average_summary_words: int = 0
