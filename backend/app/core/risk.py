from __future__ import annotations

from app.models.enums import ApprovalRiskLevel

# Risk of every action the platform knows about (sprint 2.5).
#   LOW    — the agent acts alone (read, find, draft, compute)
#   MEDIUM — needs company policy → requires approval
#   HIGH   — only a human may perform it
# Later each company will be able to override these via its own settings.
ACTION_RISK: dict[str, ApprovalRiskLevel] = {
    "prepare_sales_draft": ApprovalRiskLevel.low,
    "accept_quote": ApprovalRiskLevel.low,
    "read_message": ApprovalRiskLevel.low,
    "search_parts": ApprovalRiskLevel.low,
    "price_parts": ApprovalRiskLevel.low,
    "send_customer_message": ApprovalRiskLevel.medium,
    "create_crm_lead": ApprovalRiskLevel.medium,
    "schedule_meeting": ApprovalRiskLevel.medium,
    "send_email": ApprovalRiskLevel.medium,
    "change_price": ApprovalRiskLevel.high,
    "give_discount": ApprovalRiskLevel.high,
    "process_refund": ApprovalRiskLevel.high,
    "process_payment": ApprovalRiskLevel.high,
    "create_order": ApprovalRiskLevel.high,
    "send_supplier_order": ApprovalRiskLevel.high,
    "request_supplier_order": ApprovalRiskLevel.high,
}

_DEFAULT_RISK = ApprovalRiskLevel.medium


def risk_for(action_type: str) -> ApprovalRiskLevel:
    return ACTION_RISK.get(action_type, _DEFAULT_RISK)


def requires_approval_for(action_type: str) -> bool:
    """Actions above LOW need an ApprovalRequest before they execute."""
    return risk_for(action_type) in (ApprovalRiskLevel.medium, ApprovalRiskLevel.high)
