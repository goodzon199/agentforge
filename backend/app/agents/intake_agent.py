from __future__ import annotations

import json
import re
import uuid
from typing import Any

from pydantic import ValidationError

from app.agents.base import AgentOutput, BaseAgent
from app.llm.types import LLMMessage
from app.models import Conversation, ConversationMessage
from app.schemas.intake import IntakeResult, PartInput, VehicleInput
from app.services.intake_service import IntakeService

_VIN_RE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")
_ARTICLE_DIGITS_RE = re.compile(r"\b\d{6,}\b")
_ARTICLE_CODE_RE = re.compile(r"\b[A-Z]{1,6}[-/]?\d{2,6}\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DIGIT_RE = re.compile(r"\d+")
_ENGINE_RE = re.compile(r"двигател[ья][^.,;!?]{0,15}?(\d(?:[.,]\d)?)")
_REG_NUMBER_RE = re.compile(r"\b[А-ЯA-Z]\d{3}[А-ЯA-Z]{2}\d{2,3}\b")
_FLOAT_RE = re.compile(r"\d[.,]\d")

_NUM_WORDS = {
    "один": 1, "одна": 1, "одно": 1, "одну": 1,
    "два": 2, "две": 2, "пару": 2, "пары": 2, "двух": 2,
    "три": 3, "трёх": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
}

_BRANDS: dict[str, str] = {
    "land rover": "Land Rover", "range rover": "Land Rover",
    "volkswagen": "Volkswagen", "vw": "Volkswagen", "фольксваген": "Volkswagen",
    "mercedes": "Mercedes-Benz", "мерседес": "Mercedes-Benz",
    "chevrolet": "Chevrolet", "шкода": "Skoda",
    "toyota": "Toyota", "тойота": "Toyota", "kia": "Kia", "киа": "Kia",
    "hyundai": "Hyundai", "хендай": "Hyundai", "bmw": "BMW", "бмв": "BMW",
    "audi": "Audi", "volvo": "Volvo", "ford": "Ford", "renault": "Renault",
    "lada": "Lada", "ваз": "Lada", "nissan": "Nissan", "skoda": "Skoda",
    "seat": "SEAT", "peugeot": "Peugeot", "citroen": "Citroën", "opel": "Opel",
    "honda": "Honda", "mazda": "Mazda", "subaru": "Subaru",
    "mitsubishi": "Mitsubishi", "lexus": "Lexus", "jeep": "Jeep",
    "tesla": "Tesla", "haval": "Haval", "geely": "Geely",
    "chery": "Chery", "great wall": "Great Wall", "dongfeng": "Dongfeng",
}

_MODELS: dict[str, str] = {
    "camry": "Toyota", "corolla": "Toyota", "rav4": "Toyota",
    "land cruiser": "Toyota", "prado": "Toyota", "avensis": "Toyota",
    "rio": "Kia", "sportage": "Kia", "cerato": "Kia", "ceed": "Kia",
    "x5": "BMW", "x3": "BMW", "x6": "BMW", "xdrive": "BMW",
    "octavia": "Skoda", "fabia": "Skoda", "rapid": "Skoda", "superb": "Skoda",
    "logan": "Renault", "sandero": "Renault", "duster": "Renault",
    "kaptur": "Renault", "solaris": "Hyundai", "accent": "Hyundai",
    "tucson": "Hyundai", "creta": "Hyundai", "elantra": "Hyundai",
    "granta": "Lada", "vesta": "Lada", "priora": "Lada", "niva": "Lada",
    "passat": "Volkswagen", "golf": "Volkswagen", "polo": "Volkswagen",
    "tiguan": "Volkswagen", "jetta": "Volkswagen",
}

# (substring, canonical name, position-adjective forms)
_PART_ITEMS: list[tuple[str, str, dict[str, str]]] = [
    ("колодк", "тормозные колодки", {"передн": "передние", "задн": "задние"}),
    ("рычаг", "рычаг", {"передн": "передний", "задн": "задний"}),
    ("диск", "тормозной диск", {"передн": "передний", "задн": "задний"}),
    ("свеч", "свеча зажигания", {}),
    ("амортизатор", "амортизатор", {"передн": "передний", "задн": "задний"}),
    ("подшипник", "подшипник", {"передн": "передний", "задн": "задний"}),
    ("радиатор", "радиатор", {"передн": "передний", "задн": "задний"}),
    ("помпа", "помпа", {}),
    ("насос", "насос", {}),
    ("сальник", "сальник", {}),
    ("прокладка", "прокладка", {}),
    ("датчик", "датчик", {}),
    ("глушитель", "глушитель", {}),
    ("бампер", "бампер", {}),
    ("фара", "фара", {"передн": "передняя", "задн": "задняя"}),
    ("стекло", "стекло", {}),
    ("ремень", "ремень", {}),
    ("фильтр", "фильтр", {}),
    ("масло", "моторное масло", {}),
]

_BODY_WORDS = (
    "седан", "универсал", "хэтчбек", "купе", "кроссовер",
    "внедорожник", "лифтбек", "пикап", "минивэн",
)


class IntakeAgent(BaseAgent):
    """
    Turns a customer message into a structured PartRequest.

    Contract: returns only a valid IntakeResult. If the LLM produces a broken
    payload the agent re-prompts once with the validation error, then falls
    back to deterministic rules; low confidence escalates to a human by
    asking a clarifying question.
    """

    kind = "intake"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        if self.db is None:
            return AgentOutput(
                response="Обработка входящих сообщений недоступна без базы данных.",
                data={"action": "error", "reason": "db_missing"},
                routing_decision={"needs_agent": None, "reason": "db_missing", "engine": "intake"},
            )

        conversation_id = input_data.get("conversation_id")
        message_id = input_data.get("message_id")
        if not conversation_id or not message_id:
            return AgentOutput(
                response="Недостаточно данных для обработки сообщения.",
                data={"action": "error", "reason": "missing_ids"},
                routing_decision={"needs_agent": None, "reason": "missing_ids", "engine": "intake"},
            )

        conversation = self.db.get(Conversation, uuid.UUID(conversation_id))
        message = self.db.get(ConversationMessage, uuid.UUID(message_id))
        if conversation is None or message is None:
            return AgentOutput(
                response="Сообщение или диалог не найден.",
                data={"action": "error", "reason": "not_found"},
                routing_decision={"needs_agent": None, "reason": "not_found", "engine": "intake"},
            )

        result = self._parse(message.content, conversation=conversation)
        service = IntakeService(self.db)
        outcome = service.process(
            conversation, message, result, agent_id=self.record.id
        )
        self.db.commit()

        self.remember(
            f"Сообщение: {message.content[:80]} -> intent={result.intent}, "
            f"action={outcome.action}, ready={outcome.ready_for_search}",
            kind="intake",
        )

        data: dict[str, Any] = {
            "action": outcome.action,
            "intent": result.intent,
            "ready_for_search": outcome.ready_for_search,
            "missing_fields": outcome.missing_fields,
            "confidence": result.confidence,
        }
        if outcome.part_request is not None:
            data["part_request_id"] = str(outcome.part_request.id)
            data["status"] = outcome.part_request.status.value
        if outcome.search_task_id is not None:
            data["search_task_id"] = str(outcome.search_task_id)

        return AgentOutput(
            response=outcome.reply,
            data=data,
            routing_decision={
                "needs_agent": None,
                "reason": f"Сообщение обработано IntakeAgent ({outcome.action}).",
                "engine": "intake",
            },
            handoff_agent=None,
        )

    # --- Parsing -----------------------------------------------------------

    def _parse(
        self, text: str, conversation: Conversation | None = None
    ) -> IntakeResult:
        """LLM first (validated), deterministic rules as the fallback."""
        garage = self._garage_hint(conversation)
        if self.llm.available:
            result = self._parse_with_llm(text, garage=garage)
            if result is not None and result.confidence >= 0.5:
                return result
        return self._parse_rules(text)

    @staticmethod
    def _garage_hint(conversation: Conversation | None) -> str:
        """Sprint 4.4: list the customer's cars so the LLM can disambiguate
        a short request ("need an air filter") against the known garage."""
        if conversation is None:
            return ""
        customer = conversation.customer
        if customer is None or not getattr(customer, "vehicles", None):
            return ""
        cars = []
        for v in customer.vehicles:
            label = " ".join(
                p for p in (v.brand, v.model, str(v.year) if v.year else "") if p
            ) or "автомобиль"
            if v.vin:
                label += f" (VIN {v.vin})"
            cars.append(label)
        return "Известные автомобили клиента (гараж): " + "; ".join(cars) + "."

    def _parse_with_llm(self, text: str, *, garage: str = "") -> IntakeResult | None:
        schema = (
            '{"intent": "part_search|order_status|general_question|complaint|unknown", '
            '"vehicle": {"vin": null, "brand": null, "model": null, '
            '"year": null, "engine": null, "body": null, '
            '"registration_number": null}, '
            '"part": {"name": null, "article": null, "quantity": 1}, '
            '"missing_fields": ["vin"], "ready_for_search": false, '
            '"clarification_question": null, "confidence": 0.8}'
        )
        system_prompt = (
            "Ты — IntakeAgent, специалист по оформлению заявок на запчасти. "
            f"Извлеки из сообщения клиента структуру строго по схеме: {schema}. "
            "Правила: если VIN не указан — ready_for_search=false, в missing_fields добавь "
            "\"vin\"; если не указан автомобиль — \"vehicle\"; если не указана деталь — "
            "\"part\". Не выдумывай VIN, марку или модель. Если сообщение — продолжение "
            "диалога (например только VIN), intent=part_search. Для отсутствующих данных "
            "ставь именно JSON null — не пиши текст-заглушки вроде \"...\" или \"...|null\". "
            "Отвечай ТОЛЬКО одним JSON-объектом."
        )
        if garage:
            system_prompt += (
                f"\n{garage} Если клиент не называет автомобиль, укажи его в vehicle "
                "по контексту (например, если просит фильтр \"на мой BMW\", "
                "подставь BMW из гаража)."
            )
        for attempt in (1, 2):
            prompt = (
                f"Сообщение клиента: {text}\n"
                f"Верни JSON по схеме: {schema}"
            )
            if attempt == 2:
                prompt += "\nПредыдущий ответ не прошёл валидацию. Верни корректный JSON строго по схеме."
            try:
                result = self.llm.chat(
                    messages=[
                        LLMMessage(role="system", content=system_prompt),
                        LLMMessage(role="user", content=prompt),
                    ],
                    model=self.record.model,
                    temperature=self.record.temperature,
                    max_tokens=300,
                )
            except Exception:
                return None
            if result is None:
                return None
            parsed = self._extract_json(result.content)
            if parsed is None:
                continue
            try:
                result = IntakeResult.model_validate(parsed)
            except ValidationError:
                continue
            vin = self._extract_vin(text)
            if vin and not self._result_has_vehicle(result):
                # A bare VIN string is often missed by small models; the
                # deterministic extractor is the source of truth for it.
                return self._parse_rules(text)
            if vin and result.vehicle is not None and result.vehicle.vin is None:
                result.vehicle.vin = vin
                result.missing_fields = [
                    f for f in result.missing_fields if f != "vin"
                ]
            return result
        return None

    @staticmethod
    def _result_has_vehicle(result: IntakeResult) -> bool:
        vehicle = result.vehicle
        if vehicle is None:
            return False
        return bool(
            vehicle.vin
            or vehicle.brand
            or vehicle.model
            or vehicle.year
            or vehicle.engine
            or vehicle.registration_number
        )

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any] | None:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    # --- Rules fallback ----------------------------------------------------

    def _parse_rules(self, text: str) -> IntakeResult:
        lowered = text.lower()
        cleaned = self._clean_vins(text)

        if self._has_any(lowered, _COMPLAINT_MARKERS):
            return self._simple("complaint", text)
        if self._has_any(lowered, _ORDER_MARKERS):
            return self._simple("order_status", text)
        if self._has_any(lowered, _GENERAL_MARKERS):
            return self._simple("general_question", text)

        vin = self._extract_vin(text)
        brand, model = self._extract_vehicle(lowered)
        part_name = self._extract_part(lowered)
        article = self._extract_article(cleaned)
        year = self._extract_year(text)
        engine = self._extract_engine(text)
        body = self._extract_body(lowered)
        reg_number = self._extract_reg_number(text)
        quantity = self._extract_quantity(lowered)

        # Continuation facts (year/engine/VIN) still belong to the intake:
        # the service merges them into the active PartRequest.
        if not (vin or brand or model or part_name or article or year or engine):
            return self._simple("unknown", text)

        vehicle = VehicleInput(
            vin=vin, brand=brand, model=model, year=year,
            engine=engine, body=body, registration_number=reg_number,
        )
        part = PartInput(name=part_name or None, article=article or None, quantity=quantity)

        missing: list[str] = []
        if not part_name:
            missing.append("part")
        if not (brand or model or vin):
            missing.append("vehicle")
        elif not vin:
            missing.append("vin")
        ready = not missing

        return IntakeResult(
            intent="part_search",
            vehicle=vehicle,
            part=part,
            missing_fields=missing,
            ready_for_search=ready,
            clarification_question=None,
            confidence=0.6,
        )

    @staticmethod
    def _simple(intent: str, text: str) -> IntakeResult:
        return IntakeResult(
            intent=intent,
            vehicle=None,
            part=None,
            missing_fields=[],
            ready_for_search=False,
            clarification_question=None,
            confidence=0.7,
        )

    @staticmethod
    def _has_any(text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)

    @staticmethod
    def _clean_vins(text: str) -> str:
        return _VIN_RE.sub(" ", text)

    def _extract_vin(self, text: str) -> str | None:
        match = _VIN_RE.search(text.upper())
        return match.group(0) if match else None

    def _extract_vehicle(self, lowered: str) -> tuple[str | None, str | None]:
        brand: str | None = None
        model: str | None = None

        # Model first: "на Camry", "для Рио" — implies the brand.
        for name, implied in _MODELS.items():
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                brand, model = implied, name.title()
                break
        if brand:
            return brand, model

        for alias, canonical in sorted(_BRANDS.items(), key=lambda kv: -len(kv[0])):
            match = re.search(rf"\b{re.escape(alias)}\b", lowered)
            if match:
                brand = canonical
                tail = lowered[match.end():]
                tail_words = [w for w in tail.split() if w]
                if tail_words:
                    word = tail_words[0]
                    if not _YEAR_RE.search(word) and not _DIGIT_RE.fullmatch(word):
                        model = word.title()
                break
        return brand, model

    def _extract_part(self, lowered: str) -> str | None:
        best: tuple[int, str, dict[str, str]] | None = None
        for keyword, name, forms in _PART_ITEMS:
            index = lowered.find(keyword)
            if index == -1:
                continue
            if best is None or index < best[0]:
                best = (index, name, forms)

        if best is None:
            return None

        _, name, forms = best
        position = None
        if "передн" in lowered:
            position = "передн"
        elif "задн" in lowered:
            position = "задн"

        prefix = forms.get(position) if position else None
        if prefix:
            name = f"{prefix} {name}"

        # Type adjectives for filters.
        if name == "фильтр" or name.endswith(" фильтр"):
            if "маслян" in lowered:
                name = "масляный фильтр"
            elif "воздушн" in lowered:
                name = "воздушный фильтр"
            elif "топливн" in lowered:
                name = "топливный фильтр"
            elif "салонн" in lowered:
                name = "салонный фильтр"

        return name

    def _extract_article(self, cleaned: str) -> str | None:
        for pattern in (_ARTICLE_CODE_RE, _ARTICLE_DIGITS_RE):
            match = pattern.search(cleaned.upper())
            if match:
                return match.group(0)
        return None

    def _extract_year(self, text: str) -> int | None:
        match = _YEAR_RE.search(text)
        return int(match.group(0)) if match else None

    def _extract_engine(self, text: str) -> str | None:
        match = _ENGINE_RE.search(text)
        if match:
            return match.group(1).replace(",", ".")
        float_match = _FLOAT_RE.search(text)
        if float_match and "двигател" in text:
            return float_match.group(0).replace(",", ".")
        return None

    def _extract_body(self, lowered: str) -> str | None:
        for body in _BODY_WORDS:
            if body in lowered:
                return body
        return None

    def _extract_reg_number(self, text: str) -> str | None:
        match = _REG_NUMBER_RE.search(text.upper())
        return match.group(0) if match else None

    def _extract_quantity(self, lowered: str) -> int:
        for word, number in _NUM_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return number
        # "2 штуки", "2 комплекта", "пара".
        for match in re.finditer(
            r"(\d{1,2})\s*(?:шт|штук\w*|компл\w*|набор\w*|пару|пары)", lowered
        ):
            return int(match.group(1))
        # "Нужно 2 ...", "надо 3 ...".
        for match in re.finditer(
            r"(?:нужно|нужн[аоы]?|надо|хочу|требуется|возьми|закажи)\s+(\d{1,2})",
            lowered,
        ):
            return int(match.group(1))
        return 1


_COMPLAINT_MARKERS = (
    "жалоб", "вернуть", "возврат", "претензи", "рекламац",
    "брак", "не устроил", "не подошёл", "не подошла", "верни",
)
_ORDER_MARKERS = (
    "заказ", "где мой", "статус", "трекинг", "отследи", "когда приед",
    "когда будет", "что с моим", "заявк",
)
_GENERAL_MARKERS = (
    "работаете", "график", "когда откро", "адрес", "контакт", "телефон",
    "сколько стоит", "цена", "есть в наличии", "наличие", "доставка",
    "как купить", "привет", "здравствуйте", "спасибо",
)
