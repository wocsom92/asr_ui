from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import shutil
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypedDict

from app.config import settings
from app.database import async_session_factory
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_model import TranscriptionModel
from app.services.whisper_settings import get_whisper_cli_settings


class TranscriptionError(RuntimeError):
    pass


class TranscriptionCancelled(Exception):
    """Raised when the user cancels a job while subprocesses are running."""


ProgressCallback = Callable[[str], Awaitable[None]]
LineCallback = Callable[[str], Awaitable[None]]
PartialCallback = Callable[[list["PartialSegment"], bool], Awaitable[None]]
_WHISPER_PROGRESS_RE = re.compile(r"whisper_print_progress_callback:\s+progress =\s*(\d+)%")
_WHISPER_SEGMENT_RE = re.compile(
    r"^\s*\[(?P<start>\d{2}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[\.,]\d{3})\]\s+(?P<text>.+?)\s*$"
)
_GIGAAM_TOKENLESS_PATCH_MARKER = "# ASR_UI_TOKENLESS_LOCAL_CHUNKS"


@dataclass(frozen=True)
class GigaamChunk:
    path: Path
    input_start_seconds: float
    input_end_seconds: float
    core_start_seconds: float
    core_end_seconds: float


@dataclass(frozen=True)
class VadFrame:
    start_seconds: float
    end_seconds: float
    speech: bool
    rms: float


class PartialSegment(TypedDict):
    timestamps: dict[str, str]
    offsets: dict[str, int]
    text: str


def validate_transcription_runtime() -> None:
    executable = settings.whisper_cpp_bin
    if os.sep in executable:
        if not Path(executable).exists():
            raise TranscriptionError(
                f"whisper.cpp executable not found at {executable}. "
                "The Docker backend builds it automatically. For local dev, install "
                "whisper.cpp and set WHISPER_CPP_BIN to the local whisper-cli path."
            )
    elif shutil.which(executable) is None:
        raise TranscriptionError(
            f"whisper.cpp executable not found in PATH: {executable}. "
            "Install whisper.cpp or set WHISPER_CPP_BIN to the local whisper-cli path."
        )


def _model_provider(model: Any) -> str:
    return str(getattr(model, "provider", "") or "")


def _raise_if_cancelled(cancel_event: asyncio.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TranscriptionCancelled()


def _command_failure_message(args: tuple[str, ...], returncode: int, out: str, err: str) -> str:
    details = err.strip() or out.strip()
    if returncode < 0:
        sig_num = -returncode
        try:
            sig_name = signal.Signals(sig_num).name
        except ValueError:
            sig_name = f"SIG{sig_num}"
        if sig_num == signal.SIGKILL:
            reason = (
                "Transcription process was killed by SIGKILL. "
                "On low-memory devices this usually means the kernel OOM killer "
                "terminated whisper-cli. Try a smaller model or shorter audio."
            )
        else:
            reason = f"Command was terminated by signal {sig_name}."
        return f"{reason}\n\n{details}" if details else reason

    if returncode == 137:
        reason = (
            "Transcription process exited with code 137, which usually means "
            "it was killed due to memory pressure. Try a smaller model or shorter audio."
        )
        return f"{reason}\n\n{details}" if details else reason

    return details or f"Command failed with exit code {returncode}: {args[0]}"


def _progress_status_from_line(line: str) -> str | None:
    match = _WHISPER_PROGRESS_RE.search(line)
    if not match:
        return None
    percent = max(0, min(100, int(match.group(1))))
    return f"Transcribing {percent}%"


def _timestamp_to_ms(value: str) -> int | None:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = parts
        return int(round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))
    except ValueError:
        return None


def parse_whisper_segment_line(line: str) -> PartialSegment | None:
    match = _WHISPER_SEGMENT_RE.match(line)
    if not match:
        return None

    text = match.group("text").strip()
    if not text:
        return None

    start_text = match.group("start").replace(".", ",")
    end_text = match.group("end").replace(".", ",")
    start_ms = _timestamp_to_ms(start_text)
    end_ms = _timestamp_to_ms(end_text)
    if start_ms is None or end_ms is None:
        return None

    return {
        "timestamps": {"from": start_text, "to": end_text},
        "offsets": {"from": start_ms, "to": max(start_ms, end_ms)},
        "text": text,
    }


def _text_is_filtered(text: str, pattern: re.Pattern[str] | None) -> bool:
    return bool(pattern and pattern.search(text.strip()))


def _clean_text_output(path: Path, pattern: re.Pattern[str]) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = [line for line in lines if not _text_is_filtered(line, pattern)]
    path.write_text("\n".join(kept).strip() + ("\n" if kept else ""), encoding="utf-8")


def _clean_json_output(path: Path, pattern: re.Pattern[str]) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    segments = data.get("transcription")
    if isinstance(segments, list):
        data["transcription"] = [
            segment
            for segment in segments
            if not _text_is_filtered(str(segment.get("text", "")), pattern)
        ]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent="\t") + "\n",
        encoding="utf-8",
    )


def _subtitle_block_text(block: str) -> str:
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _clean_subtitle_output(path: Path, pattern: re.Pattern[str], *, vtt: bool) -> None:
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = raw.strip().split("\n\n") if raw.strip() else []
    header = ""
    if vtt and blocks and blocks[0].strip() == "WEBVTT":
        header = "WEBVTT\n\n"
        blocks = blocks[1:]
    kept = [block for block in blocks if not _text_is_filtered(_subtitle_block_text(block), pattern)]
    if not vtt:
        renumbered = []
        for index, block in enumerate(kept, start=1):
            lines = block.splitlines()
            if lines and lines[0].strip().isdigit():
                lines = lines[1:]
            renumbered.append("\n".join([str(index), *lines]))
        kept = renumbered
    body = "\n\n".join(kept).strip()
    path.write_text(header + body + ("\n" if body else ""), encoding="utf-8")


def _clean_transcript_outputs(
    txt_path: Path,
    json_path: Path,
    srt_path: Path,
    vtt_path: Path,
    filter_regex: str | None,
) -> None:
    if not filter_regex:
        return
    pattern = re.compile(filter_regex, re.IGNORECASE)
    _clean_text_output(txt_path, pattern)
    _clean_json_output(json_path, pattern)
    _clean_subtitle_output(srt_path, pattern, vtt=False)
    _clean_subtitle_output(vtt_path, pattern, vtt=True)


def _seconds_to_stamp(seconds: float, separator: str) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms -= 1000
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def _write_single_segment_outputs(
    text: str,
    output_base: Path,
    duration_seconds: float | None,
) -> dict[str, str | None]:
    clean_text = text.strip()
    end_seconds = max(0.0, float(duration_seconds or 0.0))
    return _write_segment_outputs(
        [
            {
                "timestamps": {
                    "from": _seconds_to_stamp(0.0, ","),
                    "to": _seconds_to_stamp(end_seconds, ","),
                },
                "offsets": {
                    "from": 0,
                    "to": int(round(end_seconds * 1000)),
                },
                "text": clean_text,
            }
        ]
        if clean_text
        else [],
        output_base,
    )


def _write_segment_outputs(
    segments: list[PartialSegment],
    output_base: Path,
) -> dict[str, str | None]:
    txt_path = output_base.with_suffix(".txt")
    json_path = output_base.with_suffix(".json")
    srt_path = output_base.with_suffix(".srt")
    vtt_path = output_base.with_suffix(".vtt")
    clean_segments = [segment for segment in segments if segment["text"].strip()]
    clean_text = "\n".join(segment["text"].strip() for segment in clean_segments)

    txt_path.write_text(clean_text + ("\n" if clean_text else ""), encoding="utf-8")
    json_path.write_text(
        json.dumps({"transcription": clean_segments}, ensure_ascii=False, indent="\t") + "\n",
        encoding="utf-8",
    )
    srt_blocks = []
    vtt_blocks = ["WEBVTT"]
    for index, segment in enumerate(clean_segments, start=1):
        start = float(segment["offsets"]["from"]) / 1000
        end = float(segment["offsets"]["to"]) / 1000
        text = segment["text"].strip()
        srt_blocks.append(
            f"{index}\n{_seconds_to_stamp(start, ',')} --> {_seconds_to_stamp(end, ',')}\n{text}"
        )
        vtt_blocks.append(
            f"{_seconds_to_stamp(start, '.')} --> {_seconds_to_stamp(end, '.')}\n{text}"
        )
    srt_path.write_text("\n\n".join(srt_blocks) + ("\n" if srt_blocks else ""), encoding="utf-8")
    vtt_path.write_text("\n\n".join(vtt_blocks) + "\n", encoding="utf-8")

    return {
        "transcript_text": clean_text,
        "output_txt_path": str(txt_path),
        "output_json_path": str(json_path),
        "output_srt_path": str(srt_path),
        "output_vtt_path": str(vtt_path),
    }


def _gigaam_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        text = result.get("text") or result.get("transcription")
        if isinstance(text, str):
            return text
        segments = result.get("segments") or result.get("chunks")
        if isinstance(segments, list):
            return _gigaam_result_to_text(segments)
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, (list, tuple)):
        parts = []
        for item in result:
            text = _gigaam_result_to_text(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(result)


def _is_gigaam_longform_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "too long wav file" in message or "transcribe_longform" in message


def _partial_segment(start_seconds: float, end_seconds: float, text: str) -> PartialSegment:
    start_ms = int(round(start_seconds * 1000))
    end_ms = max(start_ms, int(round(end_seconds * 1000)))
    return {
        "timestamps": {
            "from": _seconds_to_stamp(start_seconds, ","),
            "to": _seconds_to_stamp(end_seconds, ","),
        },
        "offsets": {"from": start_ms, "to": end_ms},
        "text": text.strip(),
    }


def _gigaam_max_seconds() -> float:
    return max(1.0, float(settings.gigaam_chunk_max_seconds))


def _gigaam_target_seconds() -> float:
    max_seconds = _gigaam_max_seconds()
    return max(1.0, min(float(settings.gigaam_chunk_target_seconds), max_seconds))


def _gigaam_overlap_seconds() -> float:
    max_seconds = _gigaam_max_seconds()
    target_seconds = _gigaam_target_seconds()
    return max(0.0, min(float(settings.gigaam_chunk_overlap_seconds), max(0.0, (max_seconds - target_seconds) / 2.0)))


def _pcm16_rms(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    sample_count = len(frame) // 2
    samples = struct.unpack(f"<{sample_count}h", frame[: sample_count * 2])
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def _wav_duration_seconds(params: wave._wave_params) -> float:
    return params.nframes / params.framerate if params.framerate > 0 else 0.0


def _write_wav_slice(
    source_frames: bytes,
    params: wave._wave_params,
    chunk_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> tuple[float, float]:
    bytes_per_frame = max(1, params.sampwidth * params.nchannels)
    start_frame = max(0, min(params.nframes, int(round(start_seconds * params.framerate))))
    end_frame = max(start_frame, min(params.nframes, int(round(end_seconds * params.framerate))))
    start_byte = start_frame * bytes_per_frame
    end_byte = end_frame * bytes_per_frame
    with wave.open(str(chunk_path), "wb") as chunk:
        chunk.setnchannels(params.nchannels)
        chunk.setsampwidth(params.sampwidth)
        chunk.setframerate(params.framerate)
        chunk.setcomptype(params.comptype, params.compname)
        chunk.writeframes(source_frames[start_byte:end_byte])
    return start_frame / params.framerate, end_frame / params.framerate


def _chunk_input_range(core_start: float, core_end: float, duration: float) -> tuple[float, float]:
    max_seconds = _gigaam_max_seconds()
    overlap = _gigaam_overlap_seconds()
    core_seconds = max(0.0, core_end - core_start)
    context_budget = max(0.0, max_seconds - core_seconds)
    before = min(overlap, core_start, context_budget / 2.0)
    after = min(overlap, duration - core_end, context_budget - before)
    before = min(before + max(0.0, context_budget - before - after), core_start, overlap)
    return max(0.0, core_start - before), min(duration, core_end + after)


def _speech_spans_from_frames(frames: list[VadFrame], duration: float) -> list[tuple[float, float]]:
    merge_gap = max(0.0, float(settings.gigaam_vad_merge_silence_ms) / 1000.0)
    pad = max(0.0, float(settings.gigaam_vad_pad_ms) / 1000.0)
    spans: list[tuple[float, float]] = []
    current_start: float | None = None
    current_end = 0.0
    for frame in frames:
        if not frame.speech:
            continue
        if current_start is None:
            current_start = frame.start_seconds
            current_end = frame.end_seconds
            continue
        if frame.start_seconds - current_end <= merge_gap:
            current_end = frame.end_seconds
        else:
            spans.append((max(0.0, current_start - pad), min(duration, current_end + pad)))
            current_start = frame.start_seconds
            current_end = frame.end_seconds
    if current_start is not None:
        spans.append((max(0.0, current_start - pad), min(duration, current_end + pad)))
    return spans


def _choose_gigaam_cut(frames: list[VadFrame], cursor: float, duration: float) -> float:
    target = _gigaam_target_seconds()
    max_seconds = _gigaam_max_seconds()
    ideal = min(duration, cursor + target)
    if duration - cursor <= max_seconds:
        return duration
    min_cut = min(duration, max(cursor + 4.0, ideal - 1.5))
    max_cut = min(duration, cursor + max_seconds, ideal + 1.5)
    if duration - max_cut < 4.0:
        return duration
    candidates = [
        frame
        for frame in frames
        if min_cut <= (frame.start_seconds + frame.end_seconds) / 2.0 <= max_cut
    ]
    if not candidates:
        return ideal
    chosen = min(
        candidates,
        key=lambda frame: (
            1 if frame.speech else 0,
            frame.rms,
            abs(((frame.start_seconds + frame.end_seconds) / 2.0) - ideal),
        ),
    )
    return max(min_cut, min(max_cut, (chosen.start_seconds + chosen.end_seconds) / 2.0))


def _plan_gigaam_core_ranges(duration: float, frames: list[VadFrame]) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    while cursor < duration:
        cut = _choose_gigaam_cut(frames, cursor, duration)
        if cut <= cursor:
            cut = min(duration, cursor + _gigaam_target_seconds())
        ranges.append((cursor, cut))
        cursor = cut
    return ranges


def _vad_frames_for_gigaam(source_frames: bytes, params: wave._wave_params) -> list[VadFrame]:
    if not settings.gigaam_vad_enabled:
        return []
    if params.nchannels != 1 or params.sampwidth != 2 or params.framerate not in {8000, 16000, 32000, 48000}:
        return []
    try:
        import webrtcvad
    except ImportError:
        return []

    vad = webrtcvad.Vad(max(0, min(3, int(settings.gigaam_vad_mode))))
    frame_ms = 30
    frame_bytes = int(params.framerate * frame_ms / 1000) * params.sampwidth * params.nchannels
    if frame_bytes <= 0:
        return []
    frames: list[VadFrame] = []
    for offset in range(0, len(source_frames) - frame_bytes + 1, frame_bytes):
        frame = source_frames[offset : offset + frame_bytes]
        frame_index = offset // max(1, params.sampwidth * params.nchannels)
        start = frame_index / params.framerate
        end = start + frame_ms / 1000
        try:
            speech = bool(vad.is_speech(frame, params.framerate))
        except Exception:
            return []
        frames.append(VadFrame(start, end, speech, _pcm16_rms(frame)))
    return frames


def _split_wav_for_gigaam_fixed(
    source_frames: bytes,
    params: wave._wave_params,
    chunks_dir: Path,
) -> list[GigaamChunk]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    duration = _wav_duration_seconds(params)
    chunks: list[GigaamChunk] = []
    cursor = 0.0
    index = 0
    while cursor < duration:
        end = min(duration, cursor + _gigaam_max_seconds())
        chunk_path = chunks_dir / f"gigaam_{index:04d}.wav"
        actual_start, actual_end = _write_wav_slice(source_frames, params, chunk_path, cursor, end)
        if actual_end <= actual_start:
            break
        chunks.append(GigaamChunk(chunk_path, actual_start, actual_end, actual_start, actual_end))
        cursor = actual_end
        index += 1
    return chunks


def _split_wav_for_gigaam(wav_path: Path, chunks_dir: Path) -> list[GigaamChunk]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "rb") as source:
        params = source.getparams()
        source_frames = source.readframes(params.nframes)

    duration = _wav_duration_seconds(params)
    frames = _vad_frames_for_gigaam(source_frames, params)
    if not frames or not _speech_spans_from_frames(frames, duration):
        return _split_wav_for_gigaam_fixed(source_frames, params, chunks_dir)

    chunks: list[GigaamChunk] = []
    for index, (core_start, core_end) in enumerate(_plan_gigaam_core_ranges(duration, frames)):
        input_start, input_end = _chunk_input_range(core_start, core_end, duration)
        if input_end - input_start > _gigaam_max_seconds() + 0.001:
            input_end = input_start + _gigaam_max_seconds()
            core_end = min(core_end, input_end)
        chunk_path = chunks_dir / f"gigaam_{index:04d}.wav"
        actual_start, actual_end = _write_wav_slice(source_frames, params, chunk_path, input_start, input_end)
        if actual_end <= actual_start:
            continue
        chunks.append(
            GigaamChunk(
                path=chunk_path,
                input_start_seconds=actual_start,
                input_end_seconds=actual_end,
                core_start_seconds=max(actual_start, core_start),
                core_end_seconds=min(actual_end, core_end),
            )
        )

    if not chunks:
        return _split_wav_for_gigaam_fixed(source_frames, params, chunks_dir)
    return chunks


_BOUNDARY_WORD_RE = re.compile(r"[\wёЁ]+", re.IGNORECASE)


def _boundary_words(text: str) -> list[str]:
    return [match.group(0).lower().replace("ё", "е") for match in _BOUNDARY_WORD_RE.finditer(text)]


def dedupe_gigaam_boundary(previous_text: str, current_text: str, max_words: int = 12) -> str:
    previous_words = _boundary_words(previous_text)
    current_words = _boundary_words(current_text)
    if not previous_words or not current_words:
        return current_text
    limit = min(max_words, len(previous_words), len(current_words))
    duplicate_words = 0
    for count in range(limit, 0, -1):
        if previous_words[-count:] == current_words[:count]:
            duplicate_words = count
            break
    if duplicate_words <= 0:
        return current_text
    tokens = current_text.split()
    if len(tokens) < duplicate_words:
        return ""
    return " ".join(tokens[duplicate_words:]).strip()


_GIGAAM_TORCH_THREADS_CONFIGURED = False


def _configure_gigaam_torch_threads(torch_module: Any) -> None:
    global _GIGAAM_TORCH_THREADS_CONFIGURED
    if _GIGAAM_TORCH_THREADS_CONFIGURED:
        return
    if settings.gigaam_torch_threads is not None:
        threads = max(1, int(settings.gigaam_torch_threads))
        torch_module.set_num_threads(threads)
    if settings.gigaam_torch_interop_threads is not None:
        interop_threads = max(1, int(settings.gigaam_torch_interop_threads))
        try:
            torch_module.set_num_interop_threads(interop_threads)
        except RuntimeError:
            pass
    _GIGAAM_TORCH_THREADS_CONFIGURED = True


def _patch_gigaam_modeling_for_tokenless_local_chunks(model_path: Path) -> None:
    modeling_path = model_path / "modeling_gigaam.py"
    if not modeling_path.exists():
        return

    text = modeling_path.read_text(encoding="utf-8", errors="replace")
    if _GIGAAM_TOKENLESS_PATCH_MARKER in text:
        return

    patched = text.replace(
        "    from pyannote.audio import Model\n"
        "    from pyannote.audio.pipelines import VoiceActivityDetection\n",
        "    import importlib\n"
        f"    {_GIGAAM_TOKENLESS_PATCH_MARKER}\n"
        "    Model = importlib.import_module(\"pyannote.audio\").Model\n"
        "    VoiceActivityDetection = importlib.import_module(\"pyannote.audio.pipelines\").VoiceActivityDetection\n",
    )
    if patched == text:
        return
    modeling_path.write_text(patched, encoding="utf-8")


async def _transcribe_gigaam(
    wav_path: Path,
    model_path: Path,
    output_base: Path,
    duration_seconds: float | None,
    cancel_event: asyncio.Event | None,
    progress_callback: ProgressCallback | None,
) -> dict[str, str | None]:
    if progress_callback is not None:
        await progress_callback("Loading GigaAM model")

    try:
        import torch
        from transformers import AutoModel
    except ImportError as exc:
        raise TranscriptionError(
            "GigaAM support requires transformers, torch, torchaudio, "
            "hydra-core, omegaconf, and sentencepiece. "
            "Rebuild the backend or worker image with updated requirements."
        ) from exc

    _raise_if_cancelled(cancel_event)
    _configure_gigaam_torch_threads(torch)

    def run() -> list[PartialSegment]:
        _patch_gigaam_modeling_for_tokenless_local_chunks(model_path)
        asr_model = AutoModel.from_pretrained(
            str(model_path),
            trust_remote_code=True,
            local_files_only=True,
        )
        audio_path = str(wav_path)

        if duration_seconds is not None and duration_seconds <= _gigaam_max_seconds():
            text = _gigaam_result_to_text(asr_model.transcribe(audio_path))
            return [_partial_segment(0.0, duration_seconds, text)] if text.strip() else []
        if duration_seconds is not None and duration_seconds > _gigaam_max_seconds():
            segments: list[PartialSegment] = []
            previous_text = ""
            for chunk in _split_wav_for_gigaam(
                wav_path,
                output_base.parent / "gigaam_chunks",
            ):
                if cancel_event is not None and cancel_event.is_set():
                    raise TranscriptionCancelled()
                raw_text = _gigaam_result_to_text(asr_model.transcribe(str(chunk.path)))
                text = dedupe_gigaam_boundary(previous_text, raw_text)
                if text.strip():
                    segments.append(_partial_segment(chunk.core_start_seconds, chunk.core_end_seconds, text))
                previous_text = raw_text
            return segments

        try:
            text = _gigaam_result_to_text(asr_model.transcribe(audio_path))
            end = max(0.0, float(duration_seconds or 0.0))
            return [_partial_segment(0.0, end, text)] if text.strip() else []
        except Exception as exc:
            if not _is_gigaam_longform_error(exc):
                raise

        segments: list[PartialSegment] = []
        previous_text = ""
        for chunk in _split_wav_for_gigaam(
            wav_path,
            output_base.parent / "gigaam_chunks",
        ):
            if cancel_event is not None and cancel_event.is_set():
                raise TranscriptionCancelled()
            raw_text = _gigaam_result_to_text(asr_model.transcribe(str(chunk.path)))
            text = dedupe_gigaam_boundary(previous_text, raw_text)
            if text.strip():
                segments.append(_partial_segment(chunk.core_start_seconds, chunk.core_end_seconds, text))
            previous_text = raw_text
        return segments

    if progress_callback is not None:
        await progress_callback("Transcribing with GigaAM")
    segments = await asyncio.to_thread(run)
    _raise_if_cancelled(cancel_event)
    if progress_callback is not None:
        await progress_callback("Transcribing 100%")
    return _write_segment_outputs(segments, output_base)


async def _read_stream(
    stream: asyncio.StreamReader | None,
    sink: list[str],
    line_callback: LineCallback | None = None,
) -> None:
    if stream is None:
        return

    while True:
        chunk = await stream.readline()
        if not chunk:
            break
        text = chunk.decode(errors="replace")
        sink.append(text)
        if line_callback is not None:
            await line_callback(text)


async def _run_command(
    *args: str,
    cancel_event: asyncio.Event | None = None,
    line_callback: LineCallback | None = None,
) -> tuple[str, str]:
    executable = args[0]
    if os.sep in executable:
        if not Path(executable).exists():
            raise TranscriptionError(
                f"Required executable is missing: {executable}. "
                "Install whisper.cpp or set WHISPER_CPP_BIN to the whisper-cli path."
            )
    elif shutil.which(executable) is None:
        raise TranscriptionError(
            f"Required executable is missing from PATH: {executable}"
        )

    _raise_if_cancelled(cancel_event)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_task = asyncio.create_task(
        _read_stream(proc.stdout, stdout_chunks, line_callback=line_callback)
    )
    stderr_task = asyncio.create_task(
        _read_stream(proc.stderr, stderr_chunks, line_callback=line_callback)
    )
    wait_task = asyncio.create_task(proc.wait())
    if cancel_event is None:
        await wait_task
    else:
        wait_cancel = asyncio.create_task(cancel_event.wait())
        _, pending = await asyncio.wait(
            {wait_task, wait_cancel},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        if wait_cancel.done() and not wait_task.done():
            if proc.returncode is None:
                proc.kill()
            await asyncio.gather(wait_task, return_exceptions=True)
            raise TranscriptionCancelled()

        await wait_task

    await asyncio.gather(stdout_task, stderr_task)

    out = "".join(stdout_chunks)
    err = "".join(stderr_chunks)
    if proc.returncode != 0:
        raise TranscriptionError(
            _command_failure_message(args, proc.returncode, out, err)
        )
    return out, err


async def transcribe_audio(
    job: TranscriptionJob,
    audio_file: AudioFile,
    model: TranscriptionModel,
    cancel_event: asyncio.Event | None = None,
    progress_callback: ProgressCallback | None = None,
    partial_callback: PartialCallback | None = None,
    output_dir: Path | None = None,
    clip_start_seconds: float | None = None,
    clip_end_seconds: float | None = None,
) -> dict[str, str | None]:
    input_path = Path(audio_file.stored_path)
    model_path = Path(model.path)
    if not input_path.exists():
        raise TranscriptionError("Uploaded audio file is missing")
    if not model_path.exists():
        raise TranscriptionError("Selected model file is missing")
    provider = _model_provider(model)
    if provider != "gigaam":
        validate_transcription_runtime()
    _raise_if_cancelled(cancel_event)
    async with async_session_factory() as settings_db:
        whisper_config = await get_whisper_cli_settings(settings_db)

    output_dir = output_dir or settings.outputs_dir / str(job.owner_user_id) / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / "input.wav"
    output_base = output_dir / "transcript"

    if progress_callback is not None:
        await progress_callback("Preparing audio")

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
    ]
    if clip_start_seconds is not None:
        ffmpeg_cmd.extend(["-ss", str(max(0.0, clip_start_seconds))])
    ffmpeg_cmd.extend([
        "-i",
        str(input_path),
    ])
    if clip_end_seconds is not None and clip_start_seconds is not None:
        duration = max(0.1, clip_end_seconds - clip_start_seconds)
        ffmpeg_cmd.extend(["-t", str(duration)])
    ffmpeg_cmd.extend([
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ])
    await _run_command(*ffmpeg_cmd, cancel_event=cancel_event)

    _raise_if_cancelled(cancel_event)
    clip_duration = (
        max(0.1, clip_end_seconds - clip_start_seconds)
        if clip_end_seconds is not None and clip_start_seconds is not None
        else getattr(audio_file, "duration_seconds", None)
    )
    if provider == "gigaam":
        outputs = await _transcribe_gigaam(
            wav_path,
            model_path,
            output_base,
            clip_duration,
            cancel_event,
            progress_callback,
        )
        _clean_transcript_outputs(
            Path(outputs["output_txt_path"]),
            Path(outputs["output_json_path"]),
            Path(outputs["output_srt_path"]),
            Path(outputs["output_vtt_path"]),
            whisper_config.transcript_filter_regex,
        )
        transcript_text = (
            Path(outputs["output_txt_path"]).read_text(encoding="utf-8", errors="replace")
            if outputs["output_txt_path"]
            else None
        )
        outputs["transcript_text"] = transcript_text
        return outputs

    if progress_callback is not None:
        await progress_callback("Loading model")

    cmd = [
        settings.whisper_cpp_bin,
        "-m",
        str(model_path),
        "-f",
        str(wav_path),
        "-t",
        str(whisper_config.whisper_threads),
        "-mc",
        str(whisper_config.whisper_max_context),
        "-otxt",
        "-osrt",
        "-ovtt",
        "-oj",
        "-of",
        str(output_base),
    ]
    if not whisper_config.whisper_use_gpu:
        cmd.append("-ng")
    if not whisper_config.whisper_flash_attn:
        cmd.append("-nfa")
    if whisper_config.whisper_suppress_non_speech:
        cmd.append("-sns")
    if whisper_config.whisper_suppress_regex:
        cmd.extend(["--suppress-regex", whisper_config.whisper_suppress_regex])
    if job.language and job.language != "auto":
        cmd.extend(["-l", job.language])
    cmd.append("-pp")

    partial_segments: list[PartialSegment] = []

    async def whisper_line_callback(line: str) -> None:
        status = _progress_status_from_line(line)
        if status is not None and progress_callback is not None:
            await progress_callback(status)
            if status.endswith("100%") and partial_callback is not None and partial_segments:
                await partial_callback(partial_segments, True)

        segment = parse_whisper_segment_line(line)
        if segment is not None and partial_callback is not None:
            partial_segments.append(segment)
            await partial_callback(partial_segments, False)

    await _run_command(
        *cmd,
        cancel_event=cancel_event,
        line_callback=whisper_line_callback,
    )
    if partial_callback is not None and partial_segments:
        await partial_callback(partial_segments, True)

    txt_path = output_base.with_suffix(".txt")
    json_path = output_base.with_suffix(".json")
    srt_path = output_base.with_suffix(".srt")
    vtt_path = output_base.with_suffix(".vtt")

    _clean_transcript_outputs(
        txt_path,
        json_path,
        srt_path,
        vtt_path,
        whisper_config.transcript_filter_regex,
    )
    transcript_text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else None
    return {
        "transcript_text": transcript_text,
        "output_txt_path": str(txt_path) if txt_path.exists() else None,
        "output_json_path": str(json_path) if json_path.exists() else None,
        "output_srt_path": str(srt_path) if srt_path.exists() else None,
        "output_vtt_path": str(vtt_path) if vtt_path.exists() else None,
    }
