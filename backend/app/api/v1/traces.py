from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Span, Trace, User
from app.schemas.trace import SpanNode, SpanRead, TraceDetail, TraceSummary, TraceTree

router = APIRouter(prefix="/traces", tags=["traces"])


def _span_node(span: Span, children_by_parent: dict[uuid.UUID | None, list[Span]]) -> SpanNode:
    return SpanNode(
        span=SpanRead.model_validate(span),
        children=[
            _span_node(child, children_by_parent)
            for child in children_by_parent.get(span.id, [])
        ],
    )


@router.get("", response_model=list[TraceSummary])
def list_traces(
    status: str | None = None,
    source: str | None = None,
    conversation_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Trace, func.count(Span.id).label("span_count"))
        .outerjoin(Span, Span.trace_id == Trace.id)
        .group_by(Trace.id)
        .order_by(Trace.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Trace.status == status)
    if source:
        stmt = stmt.where(Trace.source == source)
    if conversation_id:
        stmt = stmt.where(Trace.conversation_id == conversation_id)

    rows = db.execute(stmt).all()
    result = []
    for trace, span_count in rows:
        item = TraceSummary.model_validate(trace)
        item.span_count = span_count or 0
        item.error_kinds = list(
            {
                s.error_kind
                for s in trace.spans
                if s.status == "failed" and s.error_kind
            }
        )
        result.append(item)
    return result


@router.get("/{trace_id}", response_model=TraceTree)
def get_trace(
    trace_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace = db.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = list(trace.spans)
    children_by_parent: dict[uuid.UUID | None, list[Span]] = {}
    for sp in spans:
        children_by_parent.setdefault(sp.parent_span_id, []).append(sp)

    summary = TraceSummary.model_validate(trace)
    summary.span_count = len(spans)
    summary.error_kinds = list(
        {s.error_kind for s in spans if s.status == "failed" and s.error_kind}
    )

    root = children_by_parent.get(None)
    root_node = None
    if root:
        root_node = _span_node(root[0], children_by_parent)
    return TraceTree(trace=summary, root=root_node)
