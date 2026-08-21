from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VehicleInput(BaseModel):
    """Vehicle facts extracted from a customer message (all optional)."""

    vin: str | None = None
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    body: str | None = None
    registration_number: str | None = None


class PartInput(BaseModel):
    """Part facts extracted from a customer message."""

    name: str | None = Field(default=None, max_length=240)
    article: str | None = Field(default=None, max_length=120)
    quantity: int = Field(default=1, ge=1, le=100)


class IntakeResult(BaseModel):
    """Strict contract every IntakeAgent response must satisfy.

    The agent is forbidden from returning anything else; validation errors
    trigger a re-prompt, a rules fallback, or escalation to a human.
    """

    intent: Literal[
        "part_search",
        "order_status",
        "general_question",
        "complaint",
        "unknown",
    ] = "unknown"
    vehicle: VehicleInput | None = None
    part: PartInput | None = None
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_search: bool = False
    clarification_question: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
