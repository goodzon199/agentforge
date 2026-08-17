from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.access import company_scope, ensure_company
from app.api.deps import get_conversation_service, get_current_user
from app.models import Customer, User
from app.schemas.garage import (
    CustomerGarageRead,
    CustomerMemoryRead,
    VehicleCreate,
    VehicleRead,
)
from app.services.conversation_service import ConversationService
from app.services.garage_service import CustomerGarageService

router = APIRouter(prefix="/garage", tags=["garage"])


def _vehicle_read(vehicle) -> VehicleRead:
    return VehicleRead.model_validate(vehicle)


def _get_customer(service: ConversationService, customer_id: uuid.UUID, user: User) -> Customer:
    customer = service.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    ensure_company(user, customer.company_id)
    return customer


def _get_vehicle(garage: CustomerGarageService, vehicle_id: uuid.UUID) -> object:
    vehicle = garage.get_vehicle(vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    return vehicle


@router.get("/customers/{customer_id}", response_model=CustomerGarageRead)
def customer_garage(
    customer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    customer = _get_customer(conversations, customer_id, user)
    scope = company_scope(user)
    if scope is not None and customer.company_id != scope:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return CustomerGarageRead.model_validate(garage.garage(customer))


@router.post("/customers/{customer_id}/vehicles", response_model=VehicleRead, status_code=201)
def add_vehicle(
    customer_id: uuid.UUID,
    payload: VehicleCreate,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    customer = _get_customer(conversations, customer_id, user)
    vehicle = garage.add_vehicle(customer, **payload.model_dump())
    conversations.db.commit()
    conversations.db.refresh(vehicle)
    return _vehicle_read(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleCreate,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    vehicle = _get_vehicle(garage, vehicle_id)
    ensure_company(user, vehicle.company_id)
    garage.update_vehicle(vehicle, **payload.model_dump(exclude_unset=True))
    conversations.db.commit()
    conversations.db.refresh(vehicle)
    return _vehicle_read(vehicle)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    vehicle = _get_vehicle(garage, vehicle_id)
    ensure_company(user, vehicle.company_id)
    garage.delete_vehicle(vehicle)
    conversations.db.commit()


@router.get("/customers/{customer_id}/memory", response_model=CustomerMemoryRead)
def customer_memory(
    customer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    customer = _get_customer(conversations, customer_id, user)
    memory = garage.recompute_average_check(customer)
    conversations.db.commit()
    return CustomerMemoryRead(customer_id=customer_id, **memory)


@router.patch("/customers/{customer_id}/memory", response_model=CustomerMemoryRead)
def update_customer_memory(
    customer_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    conversations: ConversationService = Depends(get_conversation_service),
):
    garage = CustomerGarageService(conversations.db)
    customer = _get_customer(conversations, customer_id, user)
    preferences = payload.get("preferences") or {}
    if not isinstance(preferences, dict):
        raise HTTPException(status_code=422, detail="preferences должен быть объектом")
    garage.set_preferences(customer, preferences)
    memory = garage.recompute_average_check(customer)
    conversations.db.commit()
    return CustomerMemoryRead(customer_id=customer_id, **memory)
