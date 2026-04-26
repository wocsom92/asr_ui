from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import shutil
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.models.audio_file import AudioFile
from app.models.transcription_job import TranscriptionJob
from app.models.transcription_model import TranscriptionModel


class TranscriptionError(RuntimeError):
    pass


class TranscriptionCancelled(Exception):
    """Raised when the user cancels a job while subprocesses are running."""


ProgressCallback = Callable[[str], Awaitable[None]]
LineCallback = Callable[[str], Awaitable[None]]
_WHISPER_PROGRESS_RE = re.compile(r"whisper_print_progress_callback:\s+progress =\s*(\d+)%")


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
) -> None:
    if not settings.transcript_filter_regex:
        return
    pattern = re.compile(settings.transcript_filter_regex, re.IGNORECASE)
    _clean_text_output(txt_path, pattern)
    _clean_json_output(json_path, pattern)
    _clean_subtitle_output(srt_path, pattern, vtt=False)
    _clean_subtitle_output(vtt_path, pattern, vtt=True)


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
) -> dict[str, str | None]:
    input_path = Path(audio_file.stored_path)
    model_path = Path(model.path)
    if not input_path.exists():
        raise TranscriptionError("Uploaded audio file is missing")
    if not model_path.exists():
        raise TranscriptionError("Selected model file is missing")
    validate_transcription_runtime()
    _raise_if_cancelled(cancel_event)

    output_dir = settings.outputs_dir / str(job.owner_user_id) / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / "input.wav"
    output_base = output_dir / "transcript"

    if progress_callback is not None:
        await progress_callback("Preparing audio")

    await _run_command(
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
        cancel_event=cancel_event,
    )

    _raise_if_cancelled(cancel_event)
    if progress_callback is not None:
        await progress_callback("Loading model")

    cmd = [
        settings.whisper_cpp_bin,
        "-m",
        str(model_path),
        "-f",
        str(wav_path),
        "-t",
        str(settings.whisper_threads),
        "-otxt",
        "-osrt",
        "-ovtt",
        "-oj",
        "-of",
        str(output_base),
    ]
    if not settings.whisper_use_gpu:
        cmd.append("-ng")
    if not settings.whisper_flash_attn:
        cmd.append("-nfa")
    if settings.whisper_suppress_non_speech:
        cmd.append("-sns")
    if settings.whisper_suppress_regex:
        cmd.extend(["--suppress-regex", settings.whisper_suppress_regex])
    if job.language and job.language != "auto":
        cmd.extend(["-l", job.language])
    cmd.append("-pp")

    async def whisper_line_callback(line: str) -> None:
        if progress_callback is None:
            return
        status = _progress_status_from_line(line)
        if status is not None:
            await progress_callback(status)

    await _run_command(
        *cmd,
        cancel_event=cancel_event,
        line_callback=whisper_line_callback,
    )

    txt_path = output_base.with_suffix(".txt")
    json_path = output_base.with_suffix(".json")
    srt_path = output_base.with_suffix(".srt")
    vtt_path = output_base.with_suffix(".vtt")

    _clean_transcript_outputs(txt_path, json_path, srt_path, vtt_path)
    transcript_text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else None
    return {
        "transcript_text": transcript_text,
        "output_txt_path": str(txt_path) if txt_path.exists() else None,
        "output_json_path": str(json_path) if json_path.exists() else None,
        "output_srt_path": str(srt_path) if srt_path.exists() else None,
        "output_vtt_path": str(vtt_path) if vtt_path.exists() else None,
    }
