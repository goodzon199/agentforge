from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    llm_available: bool
    redis_available: bool
    generated_at: datetime
