import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.transcription_model import TranscriptionModel
from app.services.model_catalog import GIGAAM_REPO_ID, get_catalog_item, gigaam_revision

_active_installs: dict[int, asyncio.Task] = {}


def schedule_model_install(model_id: int) -> bool:
    if model_id in _active_installs:
        return False
    _active_installs[model_id] = asyncio.create_task(_install_model_guarded(model_id))
    return True


async def _install_model_guarded(model_id: int) -> None:
    try:
        await install_model(model_id)
    finally:
        _active_installs.pop(model_id, None)


async def resume_interrupted_installs() -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(TranscriptionModel).where(TranscriptionModel.status == "installing")
        )
        model_ids = [model.id for model in result.scalars().all()]
    for model_id in model_ids:
        schedule_model_install(model_id)


def is_install_active(model_id: int) -> bool:
    return model_id in _active_installs


async def cancel_model_install(model_id: int) -> bool:
    task = _active_installs.get(model_id)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async with async_session_factory() as db:
        result = await db.execute(
            select(TranscriptionModel).where(TranscriptionModel.id == model_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return False
        if model.status != "installing":
            return True
        model.status = "failed"
        model.status_text = "Install cancelled"
        model.error_message = "Model download was cancelled. Partial data is kept and can be resumed by installing again."
        await db.commit()
    return True


async def install_model(model_id: int) -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(TranscriptionModel).where(TranscriptionModel.id == model_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return

        catalog_item = get_catalog_item(model.variant)
        if not catalog_item:
            model.status = "failed"
            model.error_message = f"Unknown model variant: {model.variant}"
            await db.commit()
            return
        model.download_url = catalog_item.download_url

        target = Path(model.path)
        tmp_target = target.with_suffix(target.suffix + ".part") if target.suffix else target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if catalog_item.provider == "gigaam":
                await _install_gigaam_model(db, model, target)
                return

            if target.exists() and target.stat().st_size > 0:
                model.status = "installed"
                model.size_bytes = target.stat().st_size
                model.downloaded_bytes = target.stat().st_size
                model.total_bytes = target.stat().st_size
                model.status_text = "Already installed"
                model.installed_at = datetime.now(timezone.utc)
                model.error_message = None
                await db.commit()
                return

            model.status = "installing"
            model.downloaded_bytes = tmp_target.stat().st_size if tmp_target.exists() else 0
            model.total_bytes = None
            model.status_text = (
                "Resuming model download"
                if model.downloaded_bytes
                else "Connecting to model host"
            )
            model.error_message = None
            await db.commit()

            async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
                existing_bytes = tmp_target.stat().st_size if tmp_target.exists() else 0
                headers = {"Range": f"bytes={existing_bytes}-"} if existing_bytes else None
                async with client.stream(
                    "GET", catalog_item.download_url, headers=headers
                ) as response:
                    response.raise_for_status()
                    total = response.headers.get("content-length")
                    accepts_resume = response.status_code == 206
                    if existing_bytes and not accepts_resume:
                        tmp_target.unlink(missing_ok=True)
                        existing_bytes = 0

                    if response.headers.get("content-range"):
                        # Format: bytes start-end/total
                        total_part = response.headers["content-range"].rsplit("/", 1)[-1]
                        model.total_bytes = (
                            int(total_part) if total_part.isdigit() else None
                        )
                    elif total and total.isdigit():
                        model.total_bytes = int(total) + existing_bytes
                    else:
                        model.total_bytes = None
                    downloaded = existing_bytes
                    model.downloaded_bytes = downloaded
                    model.status_text = "Downloading model"
                    await db.commit()

                    next_commit_at = downloaded
                    mode = "ab" if existing_bytes and accepts_resume else "wb"
                    with tmp_target.open(mode) as handle:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if downloaded >= next_commit_at:
                                model.downloaded_bytes = downloaded
                                if model.total_bytes:
                                    pct = downloaded / model.total_bytes * 100
                                    model.status_text = f"Downloading model ({pct:.1f}%)"
                                else:
                                    model.status_text = "Downloading model"
                                await db.commit()
                                next_commit_at = downloaded + 2 * 1024 * 1024

            tmp_target.replace(target)
            model.status = "installed"
            model.size_bytes = target.stat().st_size
            model.downloaded_bytes = target.stat().st_size
            model.total_bytes = target.stat().st_size
            model.status_text = "Installed"
            model.installed_at = datetime.now(timezone.utc)
            model.error_message = None
        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                model.status = "failed"
                model.status_text = "Install cancelled"
                model.error_message = "Model download was cancelled. Partial data is kept and can be resumed by installing again."
                await db.commit()
                raise
            model.status = "failed"
            model.status_text = "Install failed"
            model.error_message = str(exc)

        await db.commit()


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


async def _install_gigaam_model(db, model: TranscriptionModel, target: Path) -> None:
    revision = gigaam_revision(model.variant)
    if revision is None:
        model.status = "failed"
        model.status_text = "Install failed"
        model.error_message = f"Unknown GigaAM variant: {model.variant}"
        await db.commit()
        return

    complete_marker = target / ".complete"
    if complete_marker.exists():
        size = _directory_size(target)
        model.status = "installed"
        model.size_bytes = size
        model.downloaded_bytes = size
        model.total_bytes = size
        model.status_text = "Already installed"
        model.installed_at = datetime.now(timezone.utc)
        model.error_message = None
        await db.commit()
        return

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        model.status = "failed"
        model.status_text = "Install failed"
        model.error_message = (
            "GigaAM support requires huggingface_hub, transformers, torch, "
            "torchaudio, hydra-core, omegaconf, "
            "and sentencepiece. Rebuild the backend image with updated requirements."
        )
        await db.commit()
        return

    model.status = "installing"
    model.downloaded_bytes = _directory_size(target) if target.exists() else 0
    model.total_bytes = None
    model.status_text = f"Downloading Hugging Face snapshot ({revision})"
    model.error_message = None
    await db.commit()

    await asyncio.to_thread(
        snapshot_download,
        repo_id=GIGAAM_REPO_ID,
        revision=revision,
        local_dir=str(target),
        local_dir_use_symlinks=False,
    )
    complete_marker.touch()
    size = _directory_size(target)
    model.status = "installed"
    model.size_bytes = size
    model.downloaded_bytes = size
    model.total_bytes = size
    model.status_text = "Installed"
    model.installed_at = datetime.now(timezone.utc)
    model.error_message = None
    await db.commit()
