from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.models.enums import ApprovalRiskLevel

# Every action the platform knows about, keyed by (action, resource).
#   LOW    — the agent acts alone (read, find, draft, compute)
#   MEDIUM — needs company policy → requires approval
#   HIGH   — only a human may perform it
# A company may override any of these through ``settings.permissions``:
#   {"send_customer_message": "low"}            by action
#   {"give_discount:quote": "medium"}           by action + resource
DEFAULT_POLICIES: dict[tuple[str, str | None], ApprovalRiskLevel] = {
    ("prepare_sales_draft", None): ApprovalRiskLevel.low,
    ("accept_quote", "quote"): ApprovalRiskLevel.low,
    ("read_message", "conversation"): ApprovalRiskLevel.low,
    ("search_parts", "part_request"): ApprovalRiskLevel.low,
    ("price_parts", "part_request"): ApprovalRiskLevel.low,
    # Conversation ownership changes (sprint 3 human takeover). Human-initiated,
    # recorded in the audit trail for the human-takeover-rate metric.
    ("conversation_takeover", "conversation"): ApprovalRiskLevel.low,
    ("conversation_release", "conversation"): ApprovalRiskLevel.low,
    ("conversation_pause", "conversation"): ApprovalRiskLevel.low,
    ("conversation_close", "conversation"): ApprovalRiskLevel.low,
    ("conversation_reopen", "conversation"): ApprovalRiskLevel.low,
    ("send_customer_message", None): ApprovalRiskLevel.medium,
    ("create_crm_lead", None): ApprovalRiskLevel.medium,
    ("schedule_meeting", None): ApprovalRiskLevel.medium,
    ("send_email", None): ApprovalRiskLevel.medium,
    ("change_price", None): ApprovalRiskLevel.high,
    ("give_discount", None): ApprovalRiskLevel.high,
    ("process_refund", None): ApprovalRiskLevel.high,
    ("process_payment", None): ApprovalRiskLevel.high,
    ("create_order", None): ApprovalRiskLevel.high,
    ("send_supplier_order", None): ApprovalRiskLevel.high,
    ("request_supplier_order", None): ApprovalRiskLevel.high,
}

_DEFAULT_RISK = ApprovalRiskLevel.medium

_REASONS: dict[ApprovalRiskLevel, str] = {
    ApprovalRiskLevel.low: "Низкий риск — действие разрешено агенту.",
    ApprovalRiskLevel.medium: "Действие требует согласования с менеджером.",
    ApprovalRiskLevel.high: "Действие может выполнить только человек — требуется одобрение.",
}


@dataclass(frozen=True)
class PermissionDecision:
    """Result of evaluating one action of an agent inside a company."""

    allowed: bool
    requires_approval: bool
    risk_level: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _company_settings(company) -> dict[str, Any]:
    if company is None:
        return {}
    if hasattr(company, "settings"):
        return company.settings or {}
    if isinstance(company, dict):
        return company
    return {}


def _override_risk(action: str, resource: str | None, company) -> ApprovalRiskLevel | None:
    overrides = _company_settings(company).get("permissions")
    if not isinstance(overrides, dict):
        return None
    keys = [f"{action}:{resource}", action] if resource else [action]
    for key in keys:
        raw = overrides.get(key)
        if raw is None:
            continue
        try:
            return ApprovalRiskLevel(str(raw).upper())
        except ValueError:
            # Invalid override value → ignore and fall back to defaults.
            continue
    return None


class PermissionEngine:
    """The single security mechanism for any agent, in any vertical pack.

    Every agent action is evaluated as (agent, company, action, resource,
    context) → PermissionDecision. Resolution order: company override
    (exact ``action:resource``, then ``action``) → built-in default →
    MEDIUM fallback for unknown actions.
    """

    def __init__(
        self,
        policies: Mapping[tuple[str, str | None], ApprovalRiskLevel] | None = None,
    ) -> None:
        self._policies = dict(DEFAULT_POLICIES if policies is None else policies)

    def resolve_risk(
        self, *, action: str, resource: str | None = None, company=None
    ) -> ApprovalRiskLevel:
        override = _override_risk(action, resource, company)
        if override is not None:
            return override
        for key in ((action, resource), (action, None)):
            risk = self._policies.get(key)
            if risk is not None:
                return risk
        return _DEFAULT_RISK

    def risk_for(self, action: str, resource: str | None = None, company=None) -> ApprovalRiskLevel:
        return self.resolve_risk(action=action, resource=resource, company=company)

    def requires_approval_for(
        self, action: str, resource: str | None = None, company=None
    ) -> bool:
        return self.risk_for(action, resource, company) in (
            ApprovalRiskLevel.medium,
            ApprovalRiskLevel.high,
        )

    def evaluate(
        self,
        *,
        agent=None,
        company=None,
        action: str,
        resource: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        risk = self.resolve_risk(action=action, resource=resource, company=company)
        requires_approval = risk in (ApprovalRiskLevel.medium, ApprovalRiskLevel.high)
        return PermissionDecision(
            allowed=risk is ApprovalRiskLevel.low,
            requires_approval=requires_approval,
            risk_level=risk.value,
            reason=_REASONS[risk],
        )

    def effective_policies(self, company=None) -> list[dict[str, Any]]:
        """Effective (default + company override) policy per known action."""
        result: list[dict[str, Any]] = []
        for (action, resource), default in sorted(
            DEFAULT_POLICIES.items(), key=lambda item: (item[0][0], item[0][1] or "")
        ):
            override = _override_risk(action, resource, company)
            risk = override if override is not None else default
            result.append(
                {
                    "action": action,
                    "resource": resource,
                    "risk_level": risk.value,
                    "requires_approval": risk
                    in (ApprovalRiskLevel.medium, ApprovalRiskLevel.high),
                    "source": "company" if override is not None else "default",
                }
            )
        return result


# Module-level default engine — the whole platform speaks through it.
engine = PermissionEngine()


def risk_for(action: str, resource: str | None = None, company=None) -> ApprovalRiskLevel:
    return engine.risk_for(action, resource, company)


def requires_approval_for(action: str, resource: str | None = None, company=None) -> bool:
    return engine.requires_approval_for(action, resource, company)


def evaluate(
    *,
    agent=None,
    company=None,
    action: str,
    resource: str | None = None,
    context: dict[str, Any] | None = None,
) -> PermissionDecision:
    return engine.evaluate(
        agent=agent, company=company, action=action, resource=resource, context=context
    )
