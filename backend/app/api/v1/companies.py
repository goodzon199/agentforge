from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.access import company_scope, ensure_company
from app.api.deps import get_company_service, get_current_user
from app.models import Company, User
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
        public_token=company.public_token,
        created_at=company.created_at,
        updated_at=company.updated_at,
        agents_count=len(company.agents),
        tasks_count=len(company.tasks),
    )


@router.get("", response_model=list[CompanyRead])
def list_companies(
    user: User = Depends(get_current_user),
    service: CompanyService = Depends(get_company_service),
):
    scope = company_scope(user)
    companies = service.list()
    if scope is None:
        return [_read(c) for c in companies]
    return [_read(c) for c in companies if c.id == scope]


@router.post("", response_model=CompanyRead, status_code=201)
def create_company(
    payload: CompanyCreate,
    user: User = Depends(get_current_user),
    service: CompanyService = Depends(get_company_service),
):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Только администратор может создавать компании")
    if service.get_by_slug(payload.slug):
        raise HTTPException(status_code=409, detail="Компания с таким slug уже существует")
    company = service.create(**payload.model_dump())
    service.db.commit()
    service.db.refresh(company)
    return _read(company)


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: CompanyService = Depends(get_company_service),
):
    company = service.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    ensure_company(user, company_id)
    return _read(company)


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: uuid.UUID,
    payload: CompanyUpdate,
    user: User = Depends(get_current_user),
    service: CompanyService = Depends(get_company_service),
):
    company = service.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    ensure_company(user, company_id)
    service.update(company, payload.model_dump(exclude_unset=True))
    service.db.commit()
    service.db.refresh(company)
    return _read(company)
