from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TelegramAllowedUser(BaseModel):
    telegram_user_id: int
    app_user_id: int
    preferred_worker_id: Optional[int] = None
    preferred_model_id: Optional[int] = None
    split_enabled: Optional[bool] = None
    split_worker_ids: list[int] = Field(default_factory=list)


class TelegramBotSettings(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None
    proxy_url: Optional[str] = None
    default_model_id: Optional[int] = None
    default_language: str = "auto"
    split_enabled: bool = False
    split_worker_ids: list[int] = Field(default_factory=list)
    allowed_users: list[TelegramAllowedUser] = Field(default_factory=list)


class TelegramBotSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    proxy_url: Optional[str] = None
    default_model_id: Optional[int] = None
    default_language: Optional[str] = None
    split_enabled: Optional[bool] = None
    split_worker_ids: Optional[list[int]] = None
    allowed_users: Optional[list[TelegramAllowedUser]] = None


class TelegramBotStatus(BaseModel):
    running: bool
    enabled: bool
    token_configured: bool
    token_preview: Optional[str] = None
    last_poll_at: Optional[datetime] = None
    last_error: Optional[str] = None
    update_offset: Optional[int] = None


class TelegramBotSettingsOut(BaseModel):
    enabled: bool
    proxy_url: Optional[str]
    default_model_id: Optional[int]
    default_language: str
    split_enabled: bool
    split_worker_ids: list[int]
    allowed_users: list[TelegramAllowedUser]
    token_configured: bool
    token_preview: Optional[str]
    status: TelegramBotStatus


class TelegramBotTestOut(BaseModel):
    ok: bool
    username: Optional[str] = None
    first_name: Optional[str] = None
    error: Optional[str] = None
