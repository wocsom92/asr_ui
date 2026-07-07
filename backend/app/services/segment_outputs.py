"""Shared helpers to (re)write transcript output files from canonical segments.

A canonical segment is ``{"offsets": {"from": ms, "to": ms}, "text": str, "speaker": str?}``
which matches the JSON shape produced by the transcription pipeline. Used by the
transcript editor (manual edits) and by diarization (speaker labelling) so all paths
render txt/json/srt/vtt identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.transcription_job import TranscriptionJob


def seconds_to_stamp(seconds: float, fraction_sep: str) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{fraction_sep}{millis:03d}"


def segment_display_text(segment: dict[str, Any]) -> str:
    text = str(segment.get("text", "")).strip()
    speaker = segment.get("speaker")
    if speaker:
        return f"{speaker}: {text}"
    return text


def write_segment_outputs(job: TranscriptionJob, canonical: list[dict[str, Any]]) -> None:
    """Write txt/json/srt/vtt for ``canonical`` and update the job's output fields.

    Does not commit; the caller owns the transaction.
    """
    output_dir = settings.outputs_dir / str(job.owner_user_id) / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "transcript.txt"
    json_path = output_dir / "transcript.json"
    srt_path = output_dir / "transcript.srt"
    vtt_path = output_dir / "transcript.vtt"

    transcript_text = "\n".join(segment_display_text(s) for s in canonical).strip()
    txt_path.write_text(transcript_text + ("\n" if transcript_text else ""), encoding="utf-8")
    json_path.write_text(
        json.dumps({"transcription": canonical}, ensure_ascii=False, indent="\t") + "\n",
        encoding="utf-8",
    )

    srt_blocks = []
    for index, segment in enumerate(canonical, start=1):
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        srt_blocks.append(
            f"{index}\n{seconds_to_stamp(start, ',')} --> {seconds_to_stamp(end, ',')}\n{segment_display_text(segment)}"
        )
    srt_path.write_text("\n\n".join(srt_blocks).strip() + ("\n" if srt_blocks else ""), encoding="utf-8")

    vtt_blocks = ["WEBVTT"]
    for segment in canonical:
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        vtt_blocks.append(
            f"{seconds_to_stamp(start, '.')} --> {seconds_to_stamp(end, '.')}\n{segment_display_text(segment)}"
        )
    vtt_path.write_text("\n\n".join(vtt_blocks).strip() + "\n", encoding="utf-8")

    job.transcript_text = transcript_text
    job.output_txt_path = str(txt_path)
    job.output_json_path = str(json_path)
    job.output_srt_path = str(srt_path)
    job.output_vtt_path = str(vtt_path)
