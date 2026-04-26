from __future__ import annotations

import asyncio
from pathlib import Path


SUPPORTED_AUDIO_EXTENSIONS = {
    ".m4a",
    ".aac",
    ".mp4",
    ".mov",
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".webm",
}


def is_supported_audio(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


async def probe_duration_seconds(path: Path) -> float | None:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return None
