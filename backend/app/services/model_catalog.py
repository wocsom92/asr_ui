from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.schemas.models import ModelCatalogItem


def model_url(variant: str) -> str:
    return f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{variant}.bin"


GIGAAM_REPO_ID = "ai-sage/GigaAM-v3"
GIGAAM_REVISIONS = {
    "gigaam-v3-ctc": "ctc",
    "gigaam-v3-rnnt": "rnnt",
    "gigaam-v3-e2e-ctc": "e2e_ctc",
    "gigaam-v3-e2e-rnnt": "e2e_rnnt",
}


def gigaam_url(revision: str) -> str:
    return f"https://huggingface.co/{GIGAAM_REPO_ID}/tree/{revision}"


def model_storage_path(variant: str) -> Path:
    if variant in GIGAAM_REVISIONS:
        return settings.models_dir / variant
    return settings.models_dir / f"ggml-{variant}.bin"


def gigaam_revision(variant: str) -> str | None:
    return GIGAAM_REVISIONS.get(variant)


MODEL_CATALOG: list[ModelCatalogItem] = [
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="tiny",
        display_name="Whisper tiny",
        language_mode="multilingual",
        disk_hint="75 MiB",
        ram_hint="~273 MB",
        download_url=model_url("tiny"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="tiny.ru",
        display_name="Whisper tiny Russian",
        language_mode="russian",
        disk_hint="75 MiB",
        ram_hint="~273 MB",
        download_url=model_url("tiny"),
        model_variant="tiny",
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="tiny.en",
        display_name="Whisper tiny.en",
        language_mode="english",
        disk_hint="75 MiB",
        ram_hint="~273 MB",
        download_url=model_url("tiny.en"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="base",
        display_name="Whisper base",
        language_mode="multilingual",
        disk_hint="142 MiB",
        ram_hint="~388 MB",
        download_url=model_url("base"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="base.ru",
        display_name="Whisper base Russian",
        language_mode="russian",
        disk_hint="142 MiB",
        ram_hint="~388 MB",
        download_url=model_url("base"),
        model_variant="base",
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="base.en",
        display_name="Whisper base.en",
        language_mode="english",
        disk_hint="142 MiB",
        ram_hint="~388 MB",
        download_url=model_url("base.en"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="small",
        display_name="Whisper small",
        language_mode="multilingual",
        disk_hint="466 MiB",
        ram_hint="~852 MB",
        download_url=model_url("small"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="small.ru",
        display_name="Whisper small Russian",
        language_mode="russian",
        disk_hint="466 MiB",
        ram_hint="~852 MB",
        download_url=model_url("small"),
        model_variant="small",
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="small.en",
        display_name="Whisper small.en",
        language_mode="english",
        disk_hint="466 MiB",
        ram_hint="~852 MB",
        download_url=model_url("small.en"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="medium",
        display_name="Whisper medium",
        language_mode="multilingual",
        disk_hint="1.5 GiB",
        ram_hint="~2.1 GB",
        download_url=model_url("medium"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="medium.ru",
        display_name="Whisper medium Russian",
        language_mode="russian",
        disk_hint="1.5 GiB",
        ram_hint="~2.1 GB",
        download_url=model_url("medium"),
        model_variant="medium",
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="medium.en",
        display_name="Whisper medium.en",
        language_mode="english",
        disk_hint="1.5 GiB",
        ram_hint="~2.1 GB",
        download_url=model_url("medium.en"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="large-v3",
        display_name="Whisper large-v3",
        language_mode="multilingual",
        disk_hint="2.9 GiB",
        ram_hint="~3.9 GB",
        download_url=model_url("large-v3"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="large-v3.ru",
        display_name="Whisper large-v3 Russian",
        language_mode="russian",
        disk_hint="2.9 GiB",
        ram_hint="~3.9 GB",
        download_url=model_url("large-v3"),
        model_variant="large-v3",
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="large-v3-turbo",
        display_name="Whisper large-v3-turbo",
        language_mode="multilingual",
        disk_hint="1.5 GiB",
        ram_hint="~2.1 GB",
        download_url=model_url("large-v3-turbo"),
    ),
    ModelCatalogItem(
        provider="whisper.cpp",
        variant="large-v3-turbo.ru",
        display_name="Whisper large-v3-turbo Russian",
        language_mode="russian",
        disk_hint="1.5 GiB",
        ram_hint="~2.1 GB",
        download_url=model_url("large-v3-turbo"),
        model_variant="large-v3-turbo",
    ),
    ModelCatalogItem(
        provider="gigaam",
        variant="gigaam-v3-ctc",
        display_name="GigaAM v3 CTC",
        language_mode="russian",
        disk_hint="Hugging Face snapshot",
        ram_hint="GPU or high-RAM CPU recommended",
        download_url=gigaam_url("ctc"),
    ),
    ModelCatalogItem(
        provider="gigaam",
        variant="gigaam-v3-rnnt",
        display_name="GigaAM v3 RNN-T",
        language_mode="russian",
        disk_hint="Hugging Face snapshot",
        ram_hint="GPU or high-RAM CPU recommended",
        download_url=gigaam_url("rnnt"),
    ),
    ModelCatalogItem(
        provider="gigaam",
        variant="gigaam-v3-e2e-ctc",
        display_name="GigaAM v3 E2E CTC",
        language_mode="russian",
        disk_hint="Hugging Face snapshot",
        ram_hint="GPU or high-RAM CPU recommended",
        download_url=gigaam_url("e2e_ctc"),
    ),
    ModelCatalogItem(
        provider="gigaam",
        variant="gigaam-v3-e2e-rnnt",
        display_name="GigaAM v3 E2E RNN-T",
        language_mode="russian",
        disk_hint="Hugging Face snapshot",
        ram_hint="GPU or high-RAM CPU recommended",
        download_url=gigaam_url("e2e_rnnt"),
    ),
]


def get_catalog_item(variant: str) -> ModelCatalogItem | None:
    return next((item for item in MODEL_CATALOG if item.variant == variant), None)
