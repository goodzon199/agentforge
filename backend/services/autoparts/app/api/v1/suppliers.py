from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.access import company_scope, ensure_company
from app.api.deps import (
    get_current_user,
    get_supplier_reliability_service,
    get_supplier_service,
)
from app.models import Supplier, User
from app.schemas.supplier import (
    FulfillmentRecord,
    SupplierCreate,
    SupplierFulfillmentRead,
    SupplierRead,
    SupplierReliabilityRead,
    SupplierTestResult,
    SupplierUpdate,
)
from app.services.supplier_reliability_service import SupplierReliabilityService
from app.services.supplier_service import SupplierService
from app.suppliers.registry import supplier_registry

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _read(supplier: Supplier) -> SupplierRead:
    return SupplierRead(
        id=supplier.id,
        company_id=supplier.company_id,
        name=supplier.name,
        slug=supplier.slug,
        adapter_type=supplier.adapter_type,
        is_active=supplier.is_active,
        settings=supplier.settings,
        is_experimental=supplier_registry.is_experimental(supplier.adapter_type),
        created_at=supplier.created_at,
        updated_at=supplier.updated_at,
    )


@router.get("", response_model=list[SupplierRead])
def list_suppliers(
    company_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
):
    scope = company_scope(user)
    if scope is not None:
        company_id = scope
    return [_read(s) for s in service.list(company_id=company_id)]


@router.post("", response_model=SupplierRead, status_code=201)
def create_supplier(
    payload: SupplierCreate,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
):
    ensure_company(user, payload.company_id)
    try:
        supplier = service.create(
            company_id=payload.company_id,
            name=payload.name,
            adapter_type=payload.adapter_type,
            is_active=payload.is_active,
            settings=payload.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service.db.commit()
    service.db.refresh(supplier)
    return _read(supplier)


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    return _read(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    updates = payload.model_dump(exclude_unset=True)
    if "adapter_type" in updates and updates["adapter_type"] is None:
        updates.pop("adapter_type")
    try:
        service.update(supplier, **updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service.db.commit()
    service.db.refresh(supplier)
    return _read(supplier)


@router.post("/{supplier_id}/test", response_model=SupplierTestResult)
async def test_supplier(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    return await service.test(supplier)


# --- Sprint 4.2 — Supplier Intelligence --------------------------------------


@router.get("/{supplier_id}/reliability", response_model=SupplierReliabilityRead)
def get_supplier_reliability(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
    reliability: SupplierReliabilityService = Depends(
        get_supplier_reliability_service
    ),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    return reliability.compute(supplier).to_dict()


@router.post("/{supplier_id}/recompute", response_model=SupplierReliabilityRead)
def recompute_supplier_rating(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
    reliability: SupplierReliabilityService = Depends(
        get_supplier_reliability_service
    ),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    result = reliability.refresh(supplier)
    service.db.commit()
    return result.to_dict()


@router.post("/recompute", response_model=list[SupplierReliabilityRead])
def recompute_all_supplier_ratings(
    user: User = Depends(get_current_user),
    reliability: SupplierReliabilityService = Depends(
        get_supplier_reliability_service
    ),
):
    scope = company_scope(user)
    company_id = scope if scope is not None else user.company_id
    if company_id is None:
        raise HTTPException(status_code=400, detail="Компания не определена")
    results = reliability.recompute_all(company_id)
    return [r.to_dict() for r in results]


@router.get("/{supplier_id}/fulfillments", response_model=list[SupplierFulfillmentRead])
def list_supplier_fulfillments(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
    reliability: SupplierReliabilityService = Depends(
        get_supplier_reliability_service
    ),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    from app.models import SupplierFulfillment

    rows = reliability.db.scalars(
        select(SupplierFulfillment)
        .where(SupplierFulfillment.supplier_id == supplier_id)
        .order_by(SupplierFulfillment.created_at.desc())
    ).all()
    return list(rows)


@router.post("/{supplier_id}/fulfillments", response_model=SupplierFulfillmentRead)
def record_fulfillment_actual(
    supplier_id: uuid.UUID,
    payload: FulfillmentRecord,
    user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service),
    reliability: SupplierReliabilityService = Depends(
        get_supplier_reliability_service
    ),
):
    supplier = service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    ensure_company(user, supplier.company_id)
    fulfillment = reliability.record_fulfillment_actual(
        supplier,
        fulfillment_id=payload.fulfillment_id,
        order_id=payload.order_id,
        article=payload.article,
        actual_purchase_price=payload.actual_purchase_price,
        actual_delivery_days=payload.actual_delivery_days,
        quantity_delivered=payload.quantity_delivered,
        status=payload.status,
        delivered_at=payload.delivered_at,
    )
    if fulfillment is None:
        raise HTTPException(
            status_code=404,
            detail="Строка заказа поставщика не найдена по fulfillment_id или (order_id, article)",
        )
    service.db.commit()
    service.db.refresh(fulfillment)
    return fulfillment
