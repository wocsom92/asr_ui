from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


DEFAULT_SUMMARY_SYSTEM_PROMPT = (
    "You summarize transcripts into concise meeting notes. Include: "
    "1) a short overview, 2) key points, 3) decisions, and 4) action items. "
    "Use the transcript language unless the transcript is mixed. Preserve important names, dates, and concrete commitments."
)


class SummarizationSettings(BaseModel):
    enabled: bool = False
    ollama_base_url: str = "http://ollama:11434"
    selected_model: str = ""
    auto_summarize: bool = False
    system_prompt: str = DEFAULT_SUMMARY_SYSTEM_PROMPT

    @model_validator(mode="before")
    @classmethod
    def migrate_prompt_key(cls, data):
        if isinstance(data, dict) and "system_prompt" not in data and "prompt" in data:
            data = {**data, "system_prompt": data["prompt"]}
        return data


class SummarizationSettingsUpdate(BaseModel):
    enabled: bool
    ollama_base_url: str = Field(min_length=1, max_length=500)
    selected_model: str = Field(default="", max_length=120)
    auto_summarize: bool
    system_prompt: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def migrate_prompt_key(cls, data):
        if isinstance(data, dict) and "system_prompt" not in data and "prompt" in data:
            data = {**data, "system_prompt": data["prompt"]}
        return data


class OllamaModelOut(BaseModel):
    name: str
    size: Optional[int] = None
    modified_at: Optional[str] = None


class SummarizationPullStatus(BaseModel):
    status: str = "idle"
    model: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    updated_at: Optional[datetime] = None


class SummarizationSettingsOut(SummarizationSettings):
    healthy: bool = False
    health_error: Optional[str] = None
    models: list[OllamaModelOut] = []
    recommended_models: list[str] = ["qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b"]
    pull_status: SummarizationPullStatus = SummarizationPullStatus()


class SummarizationPullIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)
