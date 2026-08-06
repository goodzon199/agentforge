from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_company_service
from app.models import Company
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate
from app.services.company_service import CompanyService

router = APIRouter(prefix="/companies", tags=["companies"])


def _read(company: Company) -> CompanyRead:
    return CompanyRead(
        id=company.id,
        name=company.name,
        slug=company.slug,
        description=company.description,
        is_active=company.is_active,
        agent_quota=company.agent_quota,
        created_at=company.created_at,
        updated_at=company.updated_at,
        agents_count=len(company.agents),
        tasks_count=len(company.tasks),
    )


@router.get("", response_model=list[CompanyRead])
def list_companies(service: CompanyService = Depends(get_company_service)):
    return [_read(c) for c in service.list()]


@router.post("", response_model=CompanyRead, status_code=201)
def create_company(
    payload: CompanyCreate,
    service: CompanyService = Depends(get_company_service),
):
    if service.get_by_slug(payload.slug):
        raise HTTPException(status_code=409, detail="Компания с таким slug уже существует")
    company = service.create(**payload.model_dump())
    service.db.commit()
    service.db.refresh(company)
    return _read(company)


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: uuid.UUID,
    service: CompanyService = Depends(get_company_service),
):
    company = service.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return _read(company)


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: uuid.UUID,
    payload: CompanyUpdate,
    service: CompanyService = Depends(get_company_service),
):
    company = service.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    service.update(company, payload.model_dump(exclude_unset=True))
    service.db.commit()
    service.db.refresh(company)
    return _read(company)
