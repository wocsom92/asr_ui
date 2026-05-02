from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.config import default_worker_name, settings
from app.database import init_db
from app.schemas.workers import WorkerModelState
from app.services.model_catalog import GIGAAM_REPO_ID, GIGAAM_REVISIONS, gigaam_revision, model_storage_path
from app.services.transcriber import TranscriptionCancelled, transcribe_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr-worker")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.asr_worker_token or ''}"}


def _model_path(variant: str) -> Path:
    return model_storage_path(variant)


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _installed_models() -> list[WorkerModelState]:
    states: list[WorkerModelState] = []
    for path in sorted(settings.models_dir.glob("ggml-*.bin")):
        variant = path.stem.removeprefix("ggml-")
        size = path.stat().st_size
        if size <= 0:
            continue
        states.append(
            WorkerModelState(
                variant=variant,
                status="installed",
                path=str(path),
                downloaded_bytes=size,
                total_bytes=size,
            )
        )
    for variant in sorted(GIGAAM_REVISIONS):
        path = _model_path(variant)
        if not (path / ".complete").exists():
            continue
        size = _directory_size(path)
        states.append(
            WorkerModelState(
                variant=variant,
                status="installed",
                path=str(path),
                downloaded_bytes=size,
                total_bytes=size,
            )
        )
    return states


async def _heartbeat(client: httpx.AsyncClient, status: str, installs: list[WorkerModelState] | None = None, last_error: str | None = None) -> None:
    await client.post(
        "/workers/heartbeat",
        json={
            "name": default_worker_name(),
            "status": status,
            "current_job_count": 1 if status in {"running", "installing", "uninstalling"} else 0,
            "models": [state.model_dump() for state in _installed_models()],
            "installs": [state.model_dump() for state in installs or []],
            "auto_install_models": settings.asr_worker_auto_install_models,
            "last_error": last_error,
        },
        headers=_headers(),
    )


async def _download_model(client: httpx.AsyncClient, variant: str, url: str) -> None:
    target = _model_path(variant)
    target.parent.mkdir(parents=True, exist_ok=True)
    revision = gigaam_revision(variant)
    if revision is not None:
        await _download_gigaam_model(client, variant, target, revision)
        return

    part = target.with_suffix(target.suffix + ".part")
    existing = part.stat().st_size if part.exists() else 0
    downloaded = existing
    total_bytes: int | None = None
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    logger.info("Installing model %s", variant)
    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as download_client:
        async with download_client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            if existing and response.status_code != 206:
                part.unlink(missing_ok=True)
                existing = 0
                downloaded = 0
            content_range = response.headers.get("content-range")
            if content_range and "/" in content_range:
                tail = content_range.rsplit("/", 1)[-1]
                total_bytes = int(tail) if tail.isdigit() else None
            else:
                content_length = response.headers.get("content-length")
                total_bytes = int(content_length) + existing if content_length and content_length.isdigit() else None

            next_report = downloaded
            with part.open("ab" if existing and response.status_code == 206 else "wb") as handle:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        await _heartbeat(
                            client,
                            "installing",
                            [
                                WorkerModelState(
                                    variant=variant,
                                    status="installing",
                                    path=str(target),
                                    downloaded_bytes=downloaded,
                                    total_bytes=total_bytes,
                                )
                            ],
                        )
                        next_report = downloaded + 2 * 1024 * 1024
    part.replace(target)
    await _heartbeat(client, "idle")
    logger.info("Installed model %s", variant)


async def _download_gigaam_model(client: httpx.AsyncClient, variant: str, target: Path, revision: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "GigaAM support requires huggingface_hub, transformers, torch, torchaudio, "
            "hydra-core, omegaconf, and sentencepiece. "
            "Rebuild the worker image with updated requirements."
        ) from exc

    logger.info("Installing GigaAM model %s (%s)", variant, revision)
    await _heartbeat(
        client,
        "installing",
        [
            WorkerModelState(
                variant=variant,
                status="installing",
                path=str(target),
                downloaded_bytes=_directory_size(target) if target.exists() else 0,
                total_bytes=None,
            )
        ],
    )
    await asyncio.to_thread(
        snapshot_download,
        repo_id=GIGAAM_REPO_ID,
        revision=revision,
        local_dir=str(target),
        local_dir_use_symlinks=False,
    )
    (target / ".complete").touch()
    size = _directory_size(target)
    await _heartbeat(
        client,
        "installing",
        [
            WorkerModelState(
                variant=variant,
                status="installed",
                path=str(target),
                downloaded_bytes=size,
                total_bytes=size,
            )
        ],
    )
    await _heartbeat(client, "idle")
    logger.info("Installed GigaAM model %s", variant)


async def _uninstall_model(client: httpx.AsyncClient, variant: str) -> None:
    await _heartbeat(client, "uninstalling")
    target = _model_path(variant)
    part = target.with_suffix(target.suffix + ".part")
    logger.info("Uninstalling model %s", variant)
    if target.is_dir():
        import shutil

        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
    part.unlink(missing_ok=True)
    await _heartbeat(client, "idle")
    logger.info("Uninstalled model %s", variant)


async def _download_audio(client: httpx.AsyncClient, kind: str, item_id: int, suffix: str = ".audio") -> Path:
    target = settings.data_dir / "worker-cache" / f"{kind}-{item_id}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    endpoint = f"/workers/jobs/{item_id}/audio" if kind == "job" else f"/workers/chunks/{item_id}/audio"
    async with client.stream(
        "GET",
        endpoint,
        params={"worker_name": default_worker_name()},
        headers=_headers(),
        timeout=None,
    ) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                if chunk:
                    handle.write(chunk)
    return target


def _read_optional(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


async def _run_claim(client: httpx.AsyncClient, claim: dict) -> None:
    kind = claim["kind"]
    item_id = claim["job_id"] if kind == "job" else claim["chunk_id"]
    if item_id is None:
        return
    cancel_event = asyncio.Event()

    async def progress_callback(status_text: str) -> None:
        endpoint = f"/workers/jobs/{item_id}/progress" if kind == "job" else f"/workers/chunks/{item_id}/progress"
        response = await client.post(
            endpoint,
            params={"worker_name": default_worker_name()},
            json={"status_text": status_text},
            headers=_headers(),
        )
        response.raise_for_status()
        if response.json().get("cancel_requested"):
            cancel_event.set()

    async def partial_callback(segments: list[dict], force: bool) -> None:
        if kind != "job":
            return
        transcript_text = "\n".join(
            str(segment.get("text", "")).strip()
            for segment in segments
            if str(segment.get("text", "")).strip()
        )
        payload = json.dumps({"transcription": segments}, ensure_ascii=False, indent="\t")
        response = await client.post(
            f"/workers/jobs/{item_id}/progress",
            params={"worker_name": default_worker_name()},
            json={
                "partial_transcript_text": transcript_text,
                "partial_transcript_json": payload,
            },
            headers=_headers(),
        )
        response.raise_for_status()
        if response.json().get("cancel_requested"):
            cancel_event.set()

    await _heartbeat(client, "running")
    audio_path = await _download_audio(client, kind, item_id)
    model_variant = claim["model_variant"]
    model_path = _model_path(model_variant)
    output_dir = settings.data_dir / "worker-output" / f"{kind}-{item_id}"
    job = SimpleNamespace(
        id=claim["job_id"],
        owner_user_id=claim["owner_user_id"],
        language=claim["language"],
    )
    audio = SimpleNamespace(stored_path=str(audio_path))
    model = SimpleNamespace(path=str(model_path), provider=("gigaam" if gigaam_revision(model_variant) else "whisper.cpp"), variant=model_variant)
    finish_endpoint = f"/workers/jobs/{item_id}/finish" if kind == "job" else f"/workers/chunks/{item_id}/finish"
    try:
        outputs = await transcribe_audio(
            job,
            audio,
            model,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
            partial_callback=partial_callback if kind == "job" else None,
            output_dir=output_dir,
            clip_start_seconds=claim.get("start_seconds"),
            clip_end_seconds=claim.get("end_seconds"),
        )
        body = {
            "status": "succeeded",
            "transcript_text": _read_optional(outputs.get("output_txt_path")) or outputs.get("transcript_text"),
            "output_json": _read_optional(outputs.get("output_json_path")),
            "output_srt": _read_optional(outputs.get("output_srt_path")),
            "output_vtt": _read_optional(outputs.get("output_vtt_path")),
        }
    except TranscriptionCancelled:
        body = {"status": "cancelled"}
    except Exception as exc:
        logger.exception("Worker failed")
        body = {"status": "failed", "error_message": str(exc)}
        await _heartbeat(client, "idle", last_error=str(exc))

    response = await client.post(
        finish_endpoint,
        params={"worker_name": default_worker_name()},
        json=body,
        headers=_headers(),
        timeout=None,
    )
    response.raise_for_status()
    await _heartbeat(client, "idle")


async def main() -> None:
    if not settings.asr_worker_token:
        raise RuntimeError("ASR_WORKER_TOKEN is required for remote worker mode")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    async with httpx.AsyncClient(base_url=settings.asr_server_url.rstrip("/") + "/api/v1", timeout=30.0) as client:
        await _heartbeat(client, "idle")
        while True:
            response = await client.post(
                "/workers/claim",
                json={
                    "name": default_worker_name(),
                    "models": [state.model_dump() for state in _installed_models()],
                    "auto_install_models": settings.asr_worker_auto_install_models,
                },
                headers=_headers(),
            )
            response.raise_for_status()
            claim = response.json()
            if claim.get("kind") == "install" and settings.asr_worker_auto_install_models:
                await _download_model(client, claim["model_variant"], claim["model_download_url"])
            elif claim.get("kind") == "uninstall":
                await _uninstall_model(client, claim["model_variant"])
            elif claim.get("kind") in {"job", "chunk"}:
                await _run_claim(client, claim)
            else:
                await _heartbeat(client, "idle")
                await asyncio.sleep(settings.transcription_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
