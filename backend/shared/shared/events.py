from __future__ import annotations

"""Inter-service event schemas.

Dataclasses only (no pydantic/SQLAlchemy) so ``shared`` stays dependency-free
and both services can import it in-process or over HTTP. The ``kind`` field is
the routing key; handlers in autoparts-service subscribe per kind.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str
    company_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "company_id": self.company_id, "payload": self.payload}


@dataclass(frozen=True)
class CustomerMessageEvent(Event):
    """A customer message arrived in a conversation (core -> autoparts)."""

    conversation_id: str
    content: str
    sender_type: str = "customer"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "customer_message")
        object.__setattr__(
            self,
            "payload",
            {
                "conversation_id": self.conversation_id,
                "content": self.content,
                "sender_type": self.sender_type,
            },
        )


@dataclass(frozen=True)
class CustomerConfirmedEvent(Event):
    """A sent quote appears accepted by the customer (core -> autoparts)."""

    quote_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "customer_confirmed")
        object.__setattr__(
            self,
            "payload",
            {"quote_id": self.quote_id, "conversation_id": self.conversation_id},
        )


@dataclass(frozen=True)
class AgentActionEvent(Event):
    """An agent action was recorded (autoparts -> core, audit idempotency)."""

    action_type: str
    target_type: str
    target_id: str
    status: str
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "agent_action")
        object.__setattr__(
            self,
            "payload",
            {
                "action_type": self.action_type,
                "target_type": self.target_type,
                "target_id": self.target_id,
                "status": self.status,
                "idempotency_key": self.idempotency_key,
            },
        )


def event_from_dict(data: dict[str, Any]) -> Event:
    kind = data.get("kind")
    if kind == "customer_message":
        return CustomerMessageEvent(
            company_id=data["company_id"],
            conversation_id=data["payload"]["conversation_id"],
            content=data["payload"]["content"],
            sender_type=data["payload"].get("sender_type", "customer"),
        )
    if kind == "customer_confirmed":
        return CustomerConfirmedEvent(
            company_id=data["company_id"],
            quote_id=data["payload"]["quote_id"],
            conversation_id=data["payload"]["conversation_id"],
        )
    if kind == "agent_action":
        return AgentActionEvent(
            company_id=data["company_id"],
            action_type=data["payload"]["action_type"],
            target_type=data["payload"]["target_type"],
            target_id=data["payload"]["target_id"],
            status=data["payload"]["status"],
            idempotency_key=data["payload"].get("idempotency_key"),
        )
    return Event(kind=kind, company_id=data["company_id"], payload=data.get("payload", {}))