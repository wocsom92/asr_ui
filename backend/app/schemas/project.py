from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=10000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=10000)
