"""Opt-in speaker diarization via pyannote.audio.

Everything here degrades gracefully: if diarization is disabled, the dependency is not
installed, or inference fails, the helpers return empty/unchanged data and log a warning
instead of breaking the transcription pipeline. Diarization is heavy (torch + a gated
Hugging Face model), so it stays off unless an admin enables it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_pipeline: Any = None
_pipeline_failed = False


def is_diarization_enabled() -> bool:
    return bool(settings.diarization_enabled)


def _load_pipeline() -> Any:
    global _pipeline, _pipeline_failed
    if _pipeline is not None or _pipeline_failed:
        return _pipeline
    try:
        from pyannote.audio import Pipeline  # type: ignore

        _pipeline = Pipeline.from_pretrained(
            settings.diarization_model,
            use_auth_token=settings.huggingface_token,
        )
    except Exception as exc:  # ImportError or model/auth/runtime failure
        _pipeline_failed = True
        logger.warning("Speaker diarization unavailable: %s", exc)
        return None
    return _pipeline


def _run_pipeline(audio_path: str) -> list[dict[str, Any]]:
    pipeline = _load_pipeline()
    if pipeline is None:
        return []
    try:
        diarization = pipeline(audio_path)
        turns: list[dict[str, Any]] = []
        for turn, _track, speaker in diarization.itertracks(yield_label=True):
            turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
        return turns
    except Exception as exc:
        logger.warning("Diarization inference failed for %s: %s", audio_path, exc)
        return []


async def diarize(audio_path: Path) -> list[dict[str, Any]]:
    """Return speaker turns ``[{start, end, speaker}]`` (empty if unavailable)."""
    if not is_diarization_enabled():
        return []
    if not audio_path or not Path(audio_path).exists():
        return []
    return await asyncio.to_thread(_run_pipeline, str(audio_path))


def assign_speakers(
    segments: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Label each canonical segment with the speaker whose turn overlaps it most.

    ``segments`` use ``offsets.from/to`` in milliseconds; ``turns`` use seconds.
    Returns a new list; segments with no overlap are left without a speaker.
    """
    if not turns:
        return segments
    labelled: list[dict[str, Any]] = []
    for segment in segments:
        seg_start = float(segment["offsets"]["from"]) / 1000
        seg_end = float(segment["offsets"]["to"]) / 1000
        best_speaker = None
        best_overlap = 0.0
        for turn in turns:
            overlap = min(seg_end, turn["end"]) - max(seg_start, turn["start"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]
        new_segment = dict(segment)
        if best_speaker is not None:
            new_segment["speaker"] = best_speaker
        labelled.append(new_segment)
    return labelled
