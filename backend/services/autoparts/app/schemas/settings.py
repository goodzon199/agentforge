from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ToolRead(BaseModel):
    name: str
    description: str
    version: str
    input_schema: dict


class MemoryContextRead(BaseModel):
    short: list[dict]
    long: list[dict]


class MemoryWrite(BaseModel):
    content: str
    kind: str = "interaction"
    memory_type: str = "short"  # short | long | knowledge
    tags: list[str] = []


class MemoryEntryRead(ORMModel):
    id: str
    agent_id: str
    memory_type: str
    content: str
    meta: dict
    created_at: str
