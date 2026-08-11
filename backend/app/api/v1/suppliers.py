from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.access import company_scope, ensure_company
from app.api.deps import get_current_user, get_supplier_service
from app.models import Supplier, User
from app.schemas.supplier import (
    SupplierCreate,
    SupplierRead,
    SupplierTestResult,
    SupplierUpdate,
)
from app.services.supplier_service import SupplierService

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
        raise HTTPException(status_code=422, detail=str(exc))
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
        raise HTTPException(status_code=422, detail=str(exc))
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
