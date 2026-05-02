from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.__version__ import __version__
from app.auth.deps import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.telegram_settings import (
    TelegramBotSettingsOut,
    TelegramBotSettingsUpdate,
    TelegramBotTestOut,
)
from app.schemas.cleanup_settings import CleanupSettingsOut, CleanupSettingsUpdate
from app.schemas.whisper_settings import WhisperCliSettingsOut, WhisperCliSettingsUpdate
from app.services.telegram_bot import (
    TelegramTransportError,
    get_bot_status,
    restart_telegram_bot,
    telegram_api_request,
)
from app.services.telegram_settings import (
    get_telegram_bot_settings,
    token_preview,
    update_telegram_bot_settings,
)
from app.services.whisper_settings import (
    default_whisper_cli_settings,
    get_whisper_cli_settings,
    reset_whisper_cli_settings,
    update_whisper_cli_settings,
    whisper_cli_preview,
)
from app.services.cleanup_settings import get_cleanup_settings, update_cleanup_settings
from app.services.job_cleanup import get_last_cleanup_deleted_count

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


@router.get("/cleanup", response_model=CleanupSettingsOut)
async def get_cleanup_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await get_cleanup_settings(db)
    return CleanupSettingsOut(
        **config.model_dump(),
        deleted_count_last_run=get_last_cleanup_deleted_count(),
    )


@router.patch("/cleanup", response_model=CleanupSettingsOut)
async def update_cleanup_config(
    body: CleanupSettingsUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await update_cleanup_settings(db, body)
    return CleanupSettingsOut(
        **config.model_dump(),
        deleted_count_last_run=get_last_cleanup_deleted_count(),
    )


@router.get("/whisper-cli", response_model=WhisperCliSettingsOut)
async def get_whisper_cli_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await get_whisper_cli_settings(db)
    return WhisperCliSettingsOut(
        **config.model_dump(),
        defaults=default_whisper_cli_settings(),
        cli_preview=whisper_cli_preview(config),
    )


@router.patch("/whisper-cli", response_model=WhisperCliSettingsOut)
async def update_whisper_cli_config(
    body: WhisperCliSettingsUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await update_whisper_cli_settings(db, body)
    return WhisperCliSettingsOut(
        **config.model_dump(),
        defaults=default_whisper_cli_settings(),
        cli_preview=whisper_cli_preview(config),
    )


@router.post("/whisper-cli/reset", response_model=WhisperCliSettingsOut)
async def reset_whisper_cli_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await reset_whisper_cli_settings(db)
    return WhisperCliSettingsOut(
        **config.model_dump(),
        defaults=default_whisper_cli_settings(),
        cli_preview=whisper_cli_preview(config),
    )


async def _telegram_settings_out(db: AsyncSession) -> TelegramBotSettingsOut:
    config = await get_telegram_bot_settings(db)
    return TelegramBotSettingsOut(
        enabled=config.enabled,
        proxy_url=config.proxy_url,
        default_model_id=config.default_model_id,
        default_language=config.default_language,
        split_enabled=config.split_enabled,
        split_worker_ids=config.split_worker_ids,
        allowed_users=config.allowed_users,
        token_configured=bool(config.bot_token),
        token_preview=token_preview(config.bot_token),
        status=await get_bot_status(),
    )


@router.get("/telegram-bot", response_model=TelegramBotSettingsOut)
async def get_telegram_bot_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _telegram_settings_out(db)


@router.patch("/telegram-bot", response_model=TelegramBotSettingsOut)
async def update_telegram_bot_config(
    body: TelegramBotSettingsUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await update_telegram_bot_settings(db, body)
    await restart_telegram_bot()
    return await _telegram_settings_out(db)


@router.post("/telegram-bot/restart", response_model=TelegramBotSettingsOut)
async def restart_telegram_bot_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await restart_telegram_bot()
    return await _telegram_settings_out(db)


@router.post("/telegram-bot/test", response_model=TelegramBotTestOut)
async def test_telegram_bot_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await get_telegram_bot_settings(db)
    if not config.bot_token:
        return TelegramBotTestOut(ok=False, error="Telegram bot token is not configured")
    try:
        response = await telegram_api_request(config, "GET", "getMe")
    except TelegramTransportError as exc:
        return TelegramBotTestOut(ok=False, error=str(exc))
    if response.status_code != 200:
        return TelegramBotTestOut(ok=False, error=response.text[:500])
    payload = response.json()
    if not payload.get("ok"):
        return TelegramBotTestOut(ok=False, error=str(payload)[:500])
    result = payload.get("result") or {}
    return TelegramBotTestOut(
        ok=True,
        username=result.get("username"),
        first_name=result.get("first_name"),
    )
