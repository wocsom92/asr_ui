import math
import wave
from pathlib import Path

import pytest

from app.services import transcriber
from app.services.transcriber import (
    VadFrame,
    _plan_gigaam_core_ranges,
    _split_wav_for_gigaam,
    dedupe_gigaam_boundary,
)


def _frames(duration: float, *, silence_from: float | None = None, silence_to: float | None = None) -> list[VadFrame]:
    frames: list[VadFrame] = []
    frame_seconds = 0.03
    count = int(duration / frame_seconds)
    for index in range(count):
        start = index * frame_seconds
        end = start + frame_seconds
        silent = silence_from is not None and silence_to is not None and silence_from <= start <= silence_to
        frames.append(VadFrame(start, end, not silent, 100.0 if not silent else 0.0))
    return frames


def _write_silent_wav(path: Path, duration: float) -> None:
    sample_rate = 16000
    sample_count = int(math.ceil(duration * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * sample_count)


def test_gigaam_planner_keeps_hour_chunks_under_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcriber.settings, "gigaam_chunk_max_seconds", 24.0)
    monkeypatch.setattr(transcriber.settings, "gigaam_chunk_target_seconds", 22.0)

    ranges = _plan_gigaam_core_ranges(3600.0, _frames(3600.0))

    assert len(ranges) > 100
    assert ranges[0][0] == 0.0
    assert ranges[-1][1] == pytest.approx(3600.0)
    assert all(end - start <= 24.001 for start, end in ranges)


def test_gigaam_planner_prefers_silence_near_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcriber.settings, "gigaam_chunk_max_seconds", 24.0)
    monkeypatch.setattr(transcriber.settings, "gigaam_chunk_target_seconds", 22.0)

    ranges = _plan_gigaam_core_ranges(50.0, _frames(50.0, silence_from=21.6, silence_to=22.4))

    assert ranges[0][1] == pytest.approx(21.615, abs=0.5)


def test_gigaam_splitter_falls_back_to_fixed_chunks_for_silence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcriber.settings, "gigaam_vad_enabled", True)
    monkeypatch.setattr(transcriber.settings, "gigaam_chunk_max_seconds", 24.0)
    wav_path = tmp_path / "silent.wav"
    _write_silent_wav(wav_path, 65.0)

    chunks = _split_wav_for_gigaam(wav_path, tmp_path / "chunks")

    assert len(chunks) == 3
    assert all(chunk.input_end_seconds - chunk.input_start_seconds <= 24.001 for chunk in chunks)
    assert [chunk.core_start_seconds for chunk in chunks] == pytest.approx([0.0, 24.0, 48.0])


def test_gigaam_boundary_dedupe_handles_russian_punctuation() -> None:
    current = dedupe_gigaam_boundary(
        "Это первый фрагмент. Привет, мир это тест!",
        "Мир это тест дальше идет текст.",
    )

    assert current == "дальше идет текст."


def test_gigaam_boundary_dedupe_keeps_distinct_text() -> None:
    current = "Совсем новый фрагмент без повтора."

    assert dedupe_gigaam_boundary("Предыдущий текст закончился.", current) == current
