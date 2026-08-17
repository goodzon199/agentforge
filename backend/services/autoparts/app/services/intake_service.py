from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMessage, Customer, PartRequest, Vehicle
from app.models.enums import PartRequestStatus
from app.schemas.intake import IntakeResult
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService
from app.services.part_request_service import PartRequestService
from app.services.task_service import TaskService

_SOURCE_OF_TRUTH_KEY = "processed_message_ids"

_PLACEHOLDER_TOKENS = frozenset(
    {
        "", "...", "..", ".", "null", "none", "n/a",
        "...|null", "...| null", "нет", "не указано",
        "отсутствует", "неизвестно", "пусто",
    }
)


def _is_placeholder(value: str) -> bool:
    """True for empty/echoed-placeholder clarifications that must not be sent
    to the customer (e.g. the LLM literally returned "...|null" or "null")."""
    question = (value or "").strip().lower()
    return (
        question in _PLACEHOLDER_TOKENS or question.startswith(("...", "|")) or question.endswith("|null")
    )


@dataclass
class IntakeOutcome:
    """What the intake did with one customer message."""

    action: str  # part_request_created | part_request_updated | already_processed | replied
    reply: str
    part_request: PartRequest | None = None
    ready_for_search: bool = False
    search_task_id: uuid.UUID | None = None
    intent: str = "unknown"
    missing_fields: list[str] | None = None


class IntakeService:
    """
    Turns a customer message into a structured PartRequest and drives the
    conversation to a searchable state.

    Source of truth lives in Conversation / ConversationMessage / PartRequest /
    Vehicle — never only in agent memory. Reprocessing the same message is
    idempotent (tracked in ``structured_data.processed_message_ids``).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public entry ------------------------------------------------------

    def process(
        self,
        conversation: Conversation,
        message: ConversationMessage,
        result: IntakeResult,
        *,
        agent_id: uuid.UUID,
    ) -> IntakeOutcome:
        # Human takeover gate: if a manager is driving (or the conversation is
        # paused/closed), the AI must not process or reply. The message itself
        # is already stored — the manager sees it and answers.
        if not ConversationService(self.db).can_agent_act(conversation):
            return IntakeOutcome(
                action="human_active",
                reply="",
                intent=result.intent,
                missing_fields=result.missing_fields,
            )

        if result.intent != "part_search":
            return self._handle_other_intent(conversation, message, result, agent_id)

        pr_service = PartRequestService(self.db)
        conv_service = ConversationService(self.db)

        # Idempotency: a message already absorbed into a request must not
        # create duplicates when processed again.
        active = pr_service.get_active_for_conversation(conversation.id)
        if active is not None:
            processed = active.structured_data.get(_SOURCE_OF_TRUTH_KEY, [])
            if str(message.id) in processed:
                return IntakeOutcome(
                    action="already_processed",
                    reply="",
                    part_request=active,
                    ready_for_search=active.status == PartRequestStatus.ready_for_search,
                    intent="part_search",
                    missing_fields=active.missing_fields,
                )

        vehicle = self._upsert_vehicle(conversation, result, active)
        self.db.flush()  # новому Vehicle присваивается id до использования
        part_request, created = self._upsert_part_request(
            conversation, message, result, vehicle, active
        )
        self.db.flush()

        # Pilot event log (sprint 3.7.1): record the funnel milestones
        # customer_message_received -> part_request_created/updated.
        self._record_audit(
            conversation=conversation,
            message=message,
            part_request=part_request,
            created=created,
            intent="part_search",
        )

        # Shadow Mode (sprint 3.8.1): open a comparison for the new request so
        # Agentos and the manager run in parallel (customer sees the manager).
        if created:
            from app.services.shadow_service import ShadowService

            ShadowService(self.db).ensure_for_part_request(part_request)

        missing = self._missing_fields(part_request, vehicle)
        ready = not missing
        part_request.missing_fields = missing
        if ready:
            part_request.status = PartRequestStatus.ready_for_search
        else:
            part_request.status = PartRequestStatus.collecting_data
        self.db.flush()

        # Fitment Engine (sprint 4.0): snapshot the real fitment confidence
        # (catalog/OEM/cross/supplier/history/manager/returns) so analytics and
        # the manager dashboard read one source of truth, not a proxy.
        from app.services.fitment_service import FitmentService

        part_request.structured_data["fitment"] = FitmentService(self.db).snapshot(part_request)
        self.db.flush()

        processed = part_request.structured_data.get(_SOURCE_OF_TRUTH_KEY, [])
        if str(message.id) not in processed:
            processed.append(str(message.id))
        part_request.structured_data[_SOURCE_OF_TRUTH_KEY] = processed
        self.db.flush()

        if ready:
            reply = self._confirmation(part_request, vehicle)
            search_task_id = self._create_search_task(conversation, part_request)
        else:
            reply = self._safe_clarification(result, missing)
            search_task_id = None

        self._agent_reply(conv_service, conversation, reply, agent_id)

        return IntakeOutcome(
            action="part_request_created" if created else "part_request_updated",
            reply=reply,
            part_request=part_request,
            ready_for_search=ready,
            search_task_id=search_task_id,
            intent="part_search",
            missing_fields=missing,
        )

    # --- Internals ---------------------------------------------------------

    def _record_audit(
        self,
        *,
        conversation: Conversation,
        message: ConversationMessage,
        part_request: PartRequest,
        created: bool,
        intent: str,
    ) -> None:
        """Append pilot-funnel milestones to the audit journal."""
        audit = AuditService(self.db)
        audit.record(
            action="customer_message_received",
            entity_type="conversation_message",
            entity_id=str(message.id),
            company_id=conversation.company_id,
            detail={
                "conversation_id": str(conversation.id),
                "intent": intent,
            },
        )
        audit.record(
            action="part_request_created" if created else "part_request_updated",
            entity_type="part_request",
            entity_id=str(part_request.id),
            company_id=conversation.company_id,
            detail={
                "conversation_id": str(conversation.id),
                "source_message_id": str(message.id),
                "ready_for_search": part_request.status
                == PartRequestStatus.ready_for_search,
            },
        )

    def _upsert_vehicle(
        self,
        conversation: Conversation,
        result: IntakeResult,
        active: PartRequest | None,
    ) -> Vehicle | None:
        v = result.vehicle
        if v is None:
            existing = self._existing_vehicle(active)
            if existing is not None:
                return existing
            return self._garage_vehicle(conversation)
        facts = {
            "vin": (v.vin or "").strip(),
            "brand": (v.brand or "").strip(),
            "model": (v.model or "").strip(),
            "year": v.year,
            "engine": (v.engine or "").strip(),
            "body": (v.body or "").strip(),
            "registration_number": (v.registration_number or "").strip(),
        }
        if not any(facts.values()):
            existing = self._existing_vehicle(active)
            if existing is not None:
                return existing
            return self._garage_vehicle(conversation)

        pr_service = PartRequestService(self.db)
        existing = (
            self._existing_vehicle(active)
            or self._garage_vehicle(conversation, result)
            or pr_service.find_vehicle(
                company_id=conversation.company_id,
                customer_id=conversation.customer_id,
                vin=facts["vin"],
                brand=facts["brand"],
                model=facts["model"],
            )
        )
        if existing is not None:
            for key, value in facts.items():
                if value:
                    setattr(existing, key, value)
            return existing
        return pr_service.create_vehicle(
            company_id=conversation.company_id,
            customer_id=conversation.customer_id,
            **facts,
        )

    def _garage_vehicle(
        self,
        conversation: Conversation,
        result: IntakeResult | None = None,
    ) -> Vehicle | None:
        """Sprint 4.4: reuse the customer's garage so a short message like
        "need an air filter" is matched to their car without re-asking.

        Prefer a garage car whose brand/model matches whatever the customer
        mentioned (e.g. "filter for the BMW"), else the default vehicle.
        """
        from app.services.garage_service import CustomerGarageService

        customer = self.db.get(Customer, conversation.customer_id)
        if customer is None:
            return None
        service = CustomerGarageService(self.db)
        vehicles = service.list_vehicles(customer)
        if not vehicles:
            return None
        if result is not None and result.vehicle is not None:
            wanted_brand = (result.vehicle.brand or "").strip().lower()
            wanted_model = (result.vehicle.model or "").strip().lower()
            for vehicle in vehicles:
                brand = (vehicle.brand or "").lower()
                model = (vehicle.model or "").lower()
                if wanted_brand and wanted_model:
                    if wanted_brand in brand and wanted_model in model:
                        return vehicle
                elif (
                    (wanted_brand
                    and wanted_brand == brand)
                    or (wanted_model
                    and wanted_model in model)
                ):
                    return vehicle
        return service.default_vehicle(customer)

    def _existing_vehicle(self, active: PartRequest | None) -> Vehicle | None:
        if active is None or active.vehicle_id is None:
            return None
        return PartRequestService(self.db).get_vehicle(active.vehicle_id)

    def _upsert_part_request(
        self,
        conversation: Conversation,
        message: ConversationMessage,
        result: IntakeResult,
        vehicle: Vehicle | None,
        active: PartRequest | None,
    ) -> tuple[PartRequest, bool]:
        pr_service = PartRequestService(self.db)
        part = result.part
        part_name = (part.name if part and part.name else "").strip()
        article = (part.article if part and part.article else "").strip()
        quantity = part.quantity if part and part.quantity else 1

        if active is not None:
            active.part_name = part_name or active.part_name
            active.article = article or active.article
            active.quantity = quantity or active.quantity
            active.source_message_id = message.id
            active.intent = "part_search"
            active.structured_data["intent_confidence"] = getattr(
                result, "confidence", None
            )
            if vehicle is not None:
                active.vehicle_id = vehicle.id
            return active, False

        part_request = pr_service.create(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            source_message_id=message.id,
            part_name=part_name,
            article=article,
            quantity=quantity,
            vehicle_id=vehicle.id if vehicle is not None else None,
            intent="part_search",
            status=PartRequestStatus.collecting_data,
            structured_data={"intent_confidence": getattr(result, "confidence", None)},
        )
        return part_request, True

    def _missing_fields(
        self, part_request: PartRequest, vehicle: Vehicle | None
    ) -> list[str]:
        missing: list[str] = []
        if not part_request.part_name:
            missing.append("part")
        if vehicle is None or not (vehicle.brand or vehicle.model or vehicle.vin):
            missing.append("vehicle")
        elif not vehicle.vin:
            missing.append("vin")
        return missing

    def _create_search_task(
        self, conversation: Conversation, part_request: PartRequest
    ) -> uuid.UUID | None:
        task_service = TaskService(self.db)
        task = task_service.create(
            company_id=conversation.company_id,
            title=f"Поиск запчасти: {part_request.part_name}",
            objective="search_parts",
            input_data={
                "part_request_id": str(part_request.id),
                "conversation_id": str(conversation.id),
                "query": part_request.part_name,
            },
        )
        self.db.add(task)
        self.db.flush()
        # Lazy import to avoid a circular dependency (intake_agent <-> orchestrator).
        from app.orchestrator.orchestrator import orchestrator

        orchestrator.submit(self.db, task)
        return task.id

    def _agent_reply(
        self,
        conv_service: ConversationService,
        conversation: Conversation,
        reply: str,
        agent_id: uuid.UUID,
    ) -> None:
        if not reply:
            return
        if not ConversationService(self.db).can_agent_act(conversation):
            return
        # sender_id is FK'd to users.id, so agent replies keep it NULL and
        # attribute the reply to the agent inside structured_data.
        conv_service.add_message(
            conversation,
            content=reply,
            sender_type="agent",
            sender_id=None,
            structured_data={"kind": "intake", "agent_id": str(agent_id)},
        )
        self.db.flush()

    def _handle_other_intent(
        self,
        conversation: Conversation,
        message: ConversationMessage,
        result: IntakeResult,
        agent_id: uuid.UUID,
    ) -> IntakeOutcome:
        reply = self._reply_for_intent(result)
        self._agent_reply(ConversationService(self.db), conversation, reply, agent_id)
        self.db.flush()
        return IntakeOutcome(
            action="replied",
            reply=reply,
            intent=result.intent,
            missing_fields=result.missing_fields,
        )

    def _reply_for_intent(self, result: IntakeResult) -> str:
        intent = result.intent
        question = (result.clarification_question or "").strip()
        if question and not _is_placeholder(question):
            return question
        if intent == "order_status":
            return (
                "Для проверки статуса заказа передам запрос сотруднику отдела продаж."
            )
        if intent == "complaint":
            return "Ваша претензия зарегистрирована, с вами свяжется сотрудник."
        if intent == "general_question":
            return "Передал вопрос сотруднику — отвечу в ближайшее время."
        return "Уточните, пожалуйста, что именно вам нужно: деталь, статус заказа или другое."

    def _safe_clarification(self, result, missing: list[str]) -> str:
        """Prefer the LLM's clarification unless it is empty or an echoed
        placeholder (e.g. the model literally returned "...|null")."""
        question = (result.clarification_question or "").strip()
        if _is_placeholder(question):
            return self._clarification(missing)
        return question

    def _clarification(self, missing: list[str]) -> str:
        if "part" in missing:
            return "Уточните, какая именно деталь вам нужна."
        if "vehicle" in missing:
            return "Уточните автомобиль: марка, модель и год выпуска."
        if "vin" in missing:
            return "Пришлите VIN автомобиля."
        return "Уточните детали запроса."

    def _confirmation(
        self, part_request: PartRequest, vehicle: Vehicle | None
    ) -> str:
        car = self._vehicle_label(vehicle)
        return (
            f"Принял: {part_request.part_name}"
            f"{' (артикул ' + part_request.article + ')' if part_request.article else ''}"
            f" x{part_request.quantity} для {car}. Начинаю поиск предложений."
        )

    @staticmethod
    def _vehicle_label(vehicle: Vehicle | None) -> str:
        if vehicle is None:
            return "автомобиль"
        parts = []
        if vehicle.brand:
            parts.append(vehicle.brand)
        if vehicle.model:
            parts.append(vehicle.model)
        if vehicle.year:
            parts.append(str(vehicle.year))
        label = " ".join(parts) or "автомобиль"
        if vehicle.vin:
            label += f" (VIN {vehicle.vin})"
        return label
