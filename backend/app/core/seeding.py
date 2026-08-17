from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    Agent,
    AgentTool,
    CatalogFitment,
    Company,
    Conversation,
    CrossReference,
    Customer,
    KnowledgeEntry,
    Order,
    PartRequest,
    PartReturn,
    Supplier,
    SupplierFulfillment,
    SupplierOffer,
    SupplierSearchAttempt,
    SupplierSearchRun,
    User,
)
from app.models.enums import AgentStatus, AgentType, PartRequestStatus
from app.orchestrator.orchestrator import SYSTEM_AGENT_SLUG
from app.services.prompt_service import DEMO_PROMPT_VERSIONS, PromptService

logger = logging.getLogger(__name__)

DEMO_COMPANY_SLUG = "demo"
DEMO_COMPANY_NAME = "Демо-компания"


def ensure_public_tokens(
    db: Session, force: list[Company] | None = None
) -> int:
    """Give every company without one a public web-chat token (idempotent)."""
    from secrets import token_urlsafe

    companies = list(force or [])
    if not companies:
        companies = list(db.scalars(select(Company)).all())
    added = 0
    for company in companies:
        if not company.public_token:
            company.public_token = token_urlsafe(16)
            added += 1
    if added:
        db.flush()
    return added

SYSTEM_AGENT_GOAL = (
    "Оркестрировать задачи: получать запросы и направлять их профильным агентам."
)
SYSTEM_AGENT_INSTRUCTIONS = (
    "Ты — SystemAgent, диспетчер. Получаешь задачу, определяешь нужного "
    "специализированного агента и возвращаешь ответ вида: "
    "'Для выполнения этой задачи нужен <AgentName>'. Сейчас ты поддерживаешь "
    "маршрутизацию к SearchAgent (поиск) и EmailAgent (почта)."
)

EMAIL_AGENT_GOAL = (
    "Отправлять письма клиентам и контрагентам по поручению SystemAgent."
)
EMAIL_AGENT_INSTRUCTIONS = (
    "Ты — EmailAgent. Получаешь задачу от SystemAgent, извлекаешь получателя "
    "(to), тему (subject) и текст письма (body) и отправляешь их через "
    "инструмент email. Если получатель не указан — используй адрес по умолчанию."
)

SEARCH_AGENT_GOAL = (
    "Находить информацию и запчасти по естественно-языковому запросу."
)
SEARCH_AGENT_INSTRUCTIONS = (
    "Ты — SearchAgent. Получаешь задачу от SystemAgent, извлекаешь поисковый "
    "запрос и ищешь по базе знаний компании (KnowledgeEntry). Если ничего не "
    "найдено — сообщаешь об этом пользователю."
)

INTAKE_AGENT_GOAL = (
    "Обрабатывать входящие сообщения клиентов и превращать их в структурированные "
    "заявки на запчасти (PartRequest)."
)
INTAKE_AGENT_INSTRUCTIONS = (
    "Ты — IntakeAgent. Получаешь сообщение клиента из диалога, извлекаешь намерение, "
    "автомобиль и деталь, возвращаешь строго валидную структуру IntakeResult. "
    "Создаёшь и обновляешь PartRequest и Vehicle, задаёшь уточняющие вопросы, "
    "при готовности передаёт заявку в поиск."
)

PRICING_AGENT_GOAL = (
    "Рассчитывать цену для клиента по предложениям поставщиков (наценка к закупке)."
)
PRICING_AGENT_INSTRUCTIONS = (
    "Ты — PricingAgent. Получаешь задачу pricing_parts с part_request_id и run_id, "
    "читаешь предложения поставщиков (SupplierOffer), применяет наценку компании к "
    "закупочной цене и сохраняет расчёт (цену за единицу, итог, лучшее предложение) "
    "в structured_data заявки."
)

SALES_AGENT_GOAL = (
    "Готовить клиенту предложение по готовой квоте (только перефразировать факты)."
)
SALES_AGENT_INSTRUCTIONS = (
    "Ты — SalesAgent. Получаешь задачу sales_draft с quote_id. Читаешь квоту "
    "(Quote.items) и составляешь вежливое сообщение клиенту со списком вариантов: "
    "бренд, артикул, цена, срок и наличие. Ты НЕ ищешь запчасти, НЕ считаешь и "
    "НЕ меняешь цены и не выдумываешь наличие. Никогда не сообщай закупочную цену "
    "и наценку. Каждое сообщение проверяет QuoteGuard."
)

# Demo supplier backend for the parts pipeline (mock, deterministic).
DEMO_SUPPLIERS = [
    {
        "name": "АвтоТорг (демо)",
        "slug": "auto-torg-demo",
        "adapter_type": "mock",
        "is_active": True,
        # Rating is on a fixed 0..1 scale (1.0 = perfect), matching the
        # auto-send supplier threshold (0.8). 0.95 = a 9.5/10 legacy rating.
        "settings": {"rating": 0.95},
    },
]

# Demo knowledge base for the search agent (auto-parts catalog samples).
DEMO_KNOWLEDGE = [
    {
        "title": "Тормозные колодки TRW GDB3410 (передние)",
        "content": (
            "Передние тормозные колодки для большинства легковых авто. "
            "Код TRW GDB3410, срок поставки 2 дня, цена 2 340 ₽/комплект."
        ),
        "tags": ["тормозные", "колодки", "trw", "тормозная система"],
    },
    {
        "title": "Масло моторное Castrol Magnatec 5W-30 (4л)",
        "content": (
            "Синтетическое моторное масло Castrol Magnatec 5W-30, API SN/CF, "
            "канистра 4 л. Артикул 15A57, цена 2 890 ₽."
        ),
        "tags": ["масло", "castrol", "моторное", "5w-30"],
    },
    {
        "title": "Фильтр масляный MANN W 712/52",
        "content": (
            "Масляный фильтр MANN-FILTER W 712/52, подходит для многих "
            "бензиновых двигателей VW/Audi/Seat/Skoda. Цена 640 ₽."
        ),
        "tags": ["фильтр", "mann", "расходники"],
    },
]

# Sprint 4.0 — demo Fitment Engine knowledge: catalog compatibility (which
# article fits which vehicle) and cross references (analog numbers). Without
# this a VIN-dependent request can never auto-send — the engine has nothing
# to prove compatibility from.
DEMO_CATALOG_FITMENTS = [
    {
        "article": "GDB3410", "brand": "TRW", "part_name": "Тормозные колодки (перед)",
        "vehicle_brand": "BMW", "vehicle_model": "X5", "year_from": 2014, "year_to": 2018,
        "engine": "N57", "source": "oem", "oem_article": "34112283435", "confidence": 0.95,
    },
    {
        "article": "GDB3410", "brand": "TRW", "part_name": "Тормозные колодки (перед)",
        "vehicle_brand": "BMW", "vehicle_model": "X6", "year_from": 2015, "year_to": 2019,
        "engine": "N57", "source": "catalog", "oem_article": "34112283435", "confidence": 0.9,
    },
    {
        "article": "P85112", "brand": "BREMBO", "part_name": "Тормозные колодки (перед)",
        "vehicle_brand": "BMW", "vehicle_model": "X5", "year_from": 2014, "year_to": 2018,
        "engine": "", "source": "catalog", "oem_article": "34112283435", "confidence": 0.85,
    },
]

DEMO_CROSS_REFERENCES = [
    {
        "source_article": "GDB3410", "source_brand": "TRW",
        "target_article": "P85112", "target_brand": "BREMBO",
        "confidence": 0.8, "source": "catalog",
    },
    {
        "source_article": "GDB3410", "source_brand": "TRW",
        "target_article": "34112283435", "target_brand": "BMW",
        "confidence": 0.95, "source": "oem",
    },
]

# Sprint 4.2 — demo reliability telemetry so the supplier scoreboard is alive
# on first launch instead of showing a blank neutral prior. The numbers mirror
# the target scoreboard: ~99.7% API availability, ~94% on-time delivery,
# ~1.8% cancellations, ~0.7% price changes.
DEMO_ATTEMPT_LATENCIES_MS = [
    320, 280, 410, 300, 350, 390, 270, 330, 380, 310,
    295, 405, 345, 315, 365, 285, 425, 305, 355, 275,
    360, 395, 290, 370, 335, 400, 310, 340, 375, 415,
]
DEMO_FULFILLMENTS = [
    # (promised_days, actual_days, promised_price, actual_price, qty_ordered, qty_delivered)
    (2, 2, "3400.00", "3400.00", 1, 1),
    (3, 3, "5120.00", "5120.00", 1, 1),
    (2, 2, "980.00", "980.00", 2, 2),
    (5, 6, "12700.00", "12700.00", 1, 1),   # 1 day late
    (2, 2, "2300.00", "2300.00", 1, 1),
    (4, 4, "6100.00", "6100.00", 1, 1),
    (2, 2, "1500.00", "1540.00", 1, 1),     # price crept up
    (3, 3, "890.00", "890.00", 4, 3),       # under-delivered
    (2, 2, "4200.00", "4200.00", 1, 1),
    (3, 4, "7600.00", "7600.00", 1, 1),     # 1 day late
    (2, 2, "1990.00", "1990.00", 1, 1),
    (2, 2, "3450.00", "3450.00", 1, 1),
    (5, 5, "8900.00", "8900.00", 1, 1),
    (2, 2, "640.00", "640.00", 3, 3),
    (3, 3, "5300.00", "5300.00", 1, 1),
    (2, 3, "2800.00", "2800.00", 1, 1),     # 1 day late
    (2, 2, "1120.00", "1120.00", 2, 2),
    (4, 4, "9500.00", "9500.00", 1, 1),
    (2, 2, "740.00", "740.00", 1, 1),
    (3, 3, "6150.00", "6150.00", 1, 1),
]


def _seed_supplier_reliability(db: Session, company: Company, supplier: Supplier) -> bool:
    """Seed demo reliability telemetry once (attempts + orders + fulfillments + returns).

    Returns True when new telemetry was created. Idempotent: if the demo
    supplier already has fulfillments, nothing is added.
    """
    from app.models.enums import (
        OrderStatus,
        SupplierAttemptStatus,
        SupplierSearchStatus,
    )

    existing = db.scalars(
        select(SupplierFulfillment).where(
            SupplierFulfillment.supplier_id == supplier.id
        )
    ).first()
    if existing is not None:
        return False

    now = datetime.now(UTC)
    created_any = False

    # A search run + attempts (API availability & latency). A lightweight part
    # request is enough — the run only needs the FK, the request never reaches
    # the funnel.
    customer = Customer(
        company_id=company.id, name="Демо-клиент", source="web"
    )
    db.add(customer)
    db.flush()
    conversation = Conversation(
        company_id=company.id,
        customer_id=customer.id,
        channel="web",
        status="closed",
    )
    db.add(conversation)
    db.flush()
    pr = PartRequest(
        company_id=company.id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        part_name="Телеметрия поставщика",
        status=PartRequestStatus.completed,
    )
    db.add(pr)
    db.flush()

    run = SupplierSearchRun(
        part_request_id=pr.id,
        status=SupplierSearchStatus.completed,
        offers_found=2,
        suppliers_succeeded=1,
        suppliers_failed=0,
        started_at=now - timedelta(days=3),
        completed_at=now - timedelta(days=3),
    )
    db.add(run)
    db.flush()

    # ~97% availability: 30 attempts, 1 failed.
    for index, latency in enumerate(DEMO_ATTEMPT_LATENCIES_MS):
        failed = index == 29
        db.add(
            SupplierSearchAttempt(
                search_run_id=run.id,
                supplier_id=supplier.id,
                status=(
                    SupplierAttemptStatus.failed
                    if failed
                    else SupplierAttemptStatus.succeeded
                ),
                offers_found=0 if failed else 2,
                error="timeout after 5000ms" if failed else "",
                latency_ms=None if failed else latency,
                started_at=now - timedelta(days=3),
                completed_at=now - timedelta(days=3),
            )
        )
    created_any = True

    # Two priced offers (so orders can be attributed to this supplier via
    # offer_id in their items).
    offers = []
    for article, brand, price in (
        ("GDB3410", "TRW", Decimal("3400.00")),
        ("P85112", "BREMBO", Decimal("6100.00")),
    ):
        offer = SupplierOffer(
            part_request_id=pr.id,
            search_run_id=run.id,
            supplier_id=supplier.id,
            brand=brand,
            article=article,
            part_name="Тормозные колодки (перед)",
            purchase_price=price,
            quantity=1,
            delivery_days=2,
            customer_price=price * Decimal("1.5"),
            total_price=price * Decimal("1.5"),
        )
        db.add(offer)
        offers.append(offer)
    db.flush()
    offers_by_article = {o.article: o for o in offers}

    # Orders: one per fulfillment line (confirmed/paid), plus two cancelled
    # orders to give the cancellation rate a real denominator.
    orders: list[Order] = []
    for idx, (promised_days, actual_days, promised_price, actual_price, qty_ordered, qty_delivered) in enumerate(DEMO_FULFILLMENTS):
        article = "GDB3410" if idx % 2 else "P85112"
        offer = offers_by_article[article]
        status = OrderStatus.paid if idx % 5 == 0 else OrderStatus.confirmed
        order = Order(
            company_id=company.id,
            conversation_id=conversation.id,
            customer_id=customer.id,
            part_request_id=pr.id,
            quote_id=None,
            order_number=f"ORD-DEMO-{idx + 1:03d}",
            status=status,
            currency="RUB",
            order_total=Decimal(actual_price) * qty_delivered,
            items=[
                {
                    "offer_id": str(offer.id),
                    "brand": offer.brand,
                    "article": offer.article,
                    "part_name": offer.part_name,
                    "sale_price": str(offer.customer_price),
                    "total_price": str(offer.customer_price),
                    "delivery_days": promised_days,
                    "quantity_available": qty_ordered,
                    "margin_percent": "50.00",
                }
            ],
            created_by_user_id=None,
            confirmed_at=now - timedelta(days=20 - idx),
        )
        db.add(order)
        orders.append(order)
        db.flush()
        db.add(
            SupplierFulfillment(
                company_id=company.id,
                supplier_id=supplier.id,
                order_id=order.id,
                offer_id=offer.id,
                article=article,
                brand=offer.brand,
                promised_purchase_price=Decimal(promised_price),
                promised_delivery_days=promised_days,
                quantity_ordered=qty_ordered,
                actual_purchase_price=Decimal(actual_price),
                actual_delivery_days=actual_days,
                quantity_delivered=qty_delivered,
                status="delivered",
                delivered_at=now - timedelta(days=20 - idx),
            )
        )

    for idx in range(2):
        cancelled = Order(
            company_id=company.id,
            conversation_id=conversation.id,
            customer_id=customer.id,
            part_request_id=pr.id,
            quote_id=None,
            order_number=f"ORD-DEMO-C{idx + 1:03d}",
            status=OrderStatus.cancelled,
            currency="RUB",
            order_total=Decimal("0.00"),
            items=[
                {
                    "offer_id": str(offers_by_article["GDB3410"].id),
                    "brand": "TRW",
                    "article": "GDB3410",
                    "part_name": "Тормозные колодки (перед)",
                    "sale_price": "5100.00",
                    "total_price": "5100.00",
                    "delivery_days": 2,
                    "quantity_available": 1,
                    "margin_percent": "50.00",
                }
            ],
            created_by_user_id=None,
        )
        db.add(cancelled)
        db.flush()

    # One attributed return (of ~20 orders -> ~5% return rate).
    db.add(
        PartReturn(
            company_id=company.id,
            supplier_id=supplier.id,
            part_request_id=pr.id,
            order_id=orders[3].id,
            article="GDB3410",
            brand="TRW",
            reason="демо: пришёл брак",
            status="returned",
            returned_at=now - timedelta(days=2),
        )
    )

    # Persist the auto-computed rating so the scoreboard shows a real number.
    from app.services.supplier_reliability_service import (
        SupplierReliabilityService,
    )

    SupplierReliabilityService(db).refresh(supplier)
    db.flush()
    return created_any


def _ensure_agent(
    db: Session,
    *,
    slug: str,
    name: str,
    role: str,
    goal: str,
    description: str,
    instructions: str,
    agent_type: AgentType,
    company_id,
    tool_names: list[str] | None = None,
) -> bool:
    agent = db.scalars(select(Agent).where(Agent.slug == slug)).first()
    if agent is not None:
        return False
    agent = Agent(
        company_id=company_id,
        name=name,
        role=role,
        slug=slug,
        goal=goal,
        description=description,
        instructions=instructions,
        type=agent_type,
        status=AgentStatus.idle,
        is_active=True,
        model=settings.default_agent_model,
        temperature=settings.default_agent_temperature,
        tools=[],
    )
    db.add(agent)
    db.flush()
    for tool_name in tool_names or []:
        db.add(AgentTool(agent_id=agent.id, tool_name=tool_name, enabled=True))
    logger.info("Создан агент %s", name)
    return True


def _ensure_prompt_versions(db: Session, company_id) -> bool:
    """Seed the demo prompt versions (v1 active) for quality comparison."""
    service = PromptService(db)
    created = False
    for agent_kind, versions in DEMO_PROMPT_VERSIONS.items():
        for index, (version, name, description, content) in enumerate(versions):
            if service._find(company_id, agent_kind, version) is not None:
                continue
            service.create(
                company_id=company_id,
                agent_kind=agent_kind,
                version=version,
                name=name,
                description=description,
                content=content,
                is_active=(index == 0),
            )
            created = True
            logger.info("Создана версия промпта %s:%s", agent_kind, version)
    return created


def _seed_customer_garage(db: Session, company: Company) -> bool:
    """Seed the demo customer "Иван" with a garage and purchase history.

    Idempotent: only creates data when the garage customer is absent. The
    customer has two cars (BMW X5, Toyota Camry), orders per car (air filter,
    oil, brake pads) and a memory blob with a middle/premium segment and an
    average check around 14 800 RUB.
    """
    from app.models import Vehicle
    from app.models.enums import OrderStatus

    existing = db.scalars(
        select(Customer).where(
            Customer.company_id == company.id,
            Customer.source == "garage-demo",
        )
    ).first()
    if existing is not None:
        return False

    now = datetime.now(UTC)
    customer = Customer(
        company_id=company.id,
        name="Иван",
        phone="+7 900 123-45-67",
        email="ivan@example.com",
        source="garage-demo",
        external_id="ivan-garage-demo",
        memory={
            "segment": "middle",
            "avg_check": 14800.0,
            "preferences": {"segment": "middle", "note": "Предпочитает средний/премиум сегмент"},
            "updated_at": now.isoformat(),
        },
    )
    db.add(customer)
    db.flush()

    vehicles = [
        Vehicle(
            company_id=company.id,
            customer_id=customer.id,
            vin="WBAKJ51000000001",
            brand="BMW",
            model="X5",
            year=2019,
            engine="B57",
            body="SUV",
            registration_number="A123BC777",
        ),
        Vehicle(
            company_id=company.id,
            customer_id=customer.id,
            vin="JTDBE3BE300000002",
            brand="Toyota",
            model="Camry",
            year=2021,
            engine="2.5",
            body="Седан",
            registration_number="B456CD777",
        ),
    ]
    for v in vehicles:
        db.add(v)
    db.flush()
    bmw, camry = vehicles

    # Two conversations so orders can be linked, then a part request + order
    # per purchase. The shop already "knows" the customer's cars, so orders
    # carry vehicle_id through the part request.
    conversation = Conversation(
        company_id=company.id,
        customer_id=customer.id,
        channel="web",
        status="closed",
    )
    db.add(conversation)
    db.flush()

    purchases = [
        (bmw, "Воздушный фильтр", "HU24010", "MANN", "1280.00", "Air filter", "9800.00"),
        (bmw, "Моторное масло", "NGN5W30", "NGN", "4350.00", "Engine oil", "12400.00"),
        (bmw, "Тормозные колодки передние", "P06089", "BREMBO", "6800.00", "Brake pads", "16800.00"),
        (camry, "Масляный фильтр", "HU13013", "MANN", "820.00", "Oil filter", "17200.00"),
        (camry, "Свеча зажигания", "90919-01248", "DENSO", "1540.00", "Spark plug", "17800.00"),
    ]
    for idx, (vehicle, part_name, article, brand, price, label, check) in enumerate(purchases):
        pr = PartRequest(
            company_id=company.id,
            conversation_id=conversation.id,
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            part_name=part_name,
            article=article,
            quantity=1,
            intent="part_search",
            status=PartRequestStatus.completed,
        )
        db.add(pr)
        db.flush()
        db.add(
            Order(
                company_id=company.id,
                conversation_id=conversation.id,
                customer_id=customer.id,
                part_request_id=pr.id,
                quote_id=None,
                order_number=f"ORD-GAR-{idx + 1:03d}",
                status=OrderStatus.paid,
                currency="RUB",
                order_total=Decimal(check),
                items=[
                    {
                        "brand": brand,
                        "article": article,
                        "part_name": part_name,
                        "total_price": price,
                        "quantity_available": 1,
                        "label": label,
                    }
                ],
                created_by_user_id=None,
                confirmed_at=now - timedelta(days=60 - idx * 10),
            )
        )
    db.flush()
    logger.info("Создан демо-гараж клиента Иван (%d авто)", len(vehicles))
    return True


def seed_demo(db: Session, *, include_customer_demo: bool = True) -> dict[str, object]:
    """Create the demo company, built-in agents and knowledge base if missing.

    ``include_customer_demo`` controls the customer-facing transactional demo
    data (supplier reliability telemetry + the garage customer). It defaults
    to True so dev/prod demos get the rich data; tests disable it so they do
    not depend on demo customers/orders in global queries.
    """
    created = {
        "company": False,
        "system_agent": False,
        "email_agent": False,
        "search_agent": False,
        "intake_agent": False,
        "pricing_agent": False,
        "sales_agent": False,
        "prompts": False,
        "knowledge": False,
        "suppliers": False,
        "supplier_reliability": False,
        "fitment": False,
        "garage": False,
        "admin": False,
    }

    company = db.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    if company is None:
        company = Company(
            name=DEMO_COMPANY_NAME,
            slug=DEMO_COMPANY_SLUG,
            description="Компания по умолчанию для первого запуска платформы.",
            is_active=True,
            agent_quota=10,
        )
        db.add(company)
        db.flush()
        created["company"] = True
        logger.info("Создана демо-компания '%s'", DEMO_COMPANY_NAME)

    # Web-chat widget needs a public token; backfill any company without one.
    ensure_public_tokens(db, force=[company])

    created["system_agent"] = _ensure_agent(
        db,
        slug=SYSTEM_AGENT_SLUG,
        name="SystemAgent",
        role="Диспетчер и роутер задач",
        goal=SYSTEM_AGENT_GOAL,
        description=(
            "Первый агент платформы. Получает задачу и определяет, какой "
            "специализированный агент нужен для её выполнения."
        ),
        instructions=SYSTEM_AGENT_INSTRUCTIONS,
        agent_type=AgentType.system,
        company_id=company.id,
    )

    created["email_agent"] = _ensure_agent(
        db,
        slug="email-agent",
        name="EmailAgent",
        role="Отправка электронных писем",
        goal=EMAIL_AGENT_GOAL,
        description=(
            "Специализированный агент: превращает задачу в письмо и отправляет "
            "его через SMTP (в демо-стеке — MailHog)."
        ),
        instructions=EMAIL_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
        tool_names=["email"],
    )

    created["search_agent"] = _ensure_agent(
        db,
        slug="search-agent",
        name="SearchAgent",
        role="Поиск информации и запчастей",
        goal=SEARCH_AGENT_GOAL,
        description=(
            "Специализированный агент: ищет информацию по базе знаний компании "
            "(KnowledgeEntry). Внешние каталоги подключаются через инструмент search."
        ),
        instructions=SEARCH_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
        tool_names=["search"],
    )

    created["intake_agent"] = _ensure_agent(
        db,
        slug="intake-agent",
        name="IntakeAgent",
        role="Обработка входящих сообщений клиентов",
        goal=INTAKE_AGENT_GOAL,
        description=(
            "Специализированный агент: превращает сообщение клиента в структурированную "
            "заявку на запчасть (PartRequest), уточняет данные и передаёт заявку в поиск."
        ),
        instructions=INTAKE_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
    )

    created["pricing_agent"] = _ensure_agent(
        db,
        slug="pricing-agent",
        name="PricingAgent",
        role="Расчёт цены по предложениям поставщиков",
        goal=PRICING_AGENT_GOAL,
        description=(
            "Специализированный агент: рассчитывает клиентскую цену (наценка к "
            "закупочной) по предложениям поставщиков и сохраняет расчёт в заявке."
        ),
        instructions=PRICING_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
    )

    created["sales_agent"] = _ensure_agent(
        db,
        slug="sales-agent",
        name="SalesAgent",
        role="Подготовка предложения клиенту по готовой квоте",
        goal=SALES_AGENT_GOAL,
        description=(
            "Специализированный агент: превращает готовую квоту (расчёт цен) в "
            "вежливое предложение клиенту. Не меняет цены и наличие; каждое "
            "сообщение проверяет QuoteGuard."
        ),
        instructions=SALES_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
    )

    created["prompts"] = _ensure_prompt_versions(db, company.id)

    knowledge_count = db.scalars(
        select(KnowledgeEntry).where(KnowledgeEntry.company_id == company.id)
    ).all()
    if not knowledge_count:
        for item in DEMO_KNOWLEDGE:
            db.add(
                KnowledgeEntry(
                    company_id=company.id,
                    title=item["title"],
                    content=item["content"],
                    tags=item["tags"],
                )
            )
        created["knowledge"] = True
        logger.info("Создана демо-база знаний (%d записей)", len(DEMO_KNOWLEDGE))

    supplier_count = db.scalars(
        select(Supplier).where(Supplier.company_id == company.id)
    ).all()
    if not supplier_count:
        for item in DEMO_SUPPLIERS:
            db.add(
                Supplier(
                    company_id=company.id,
                    name=item["name"],
                    slug=item["slug"],
                    adapter_type=item["adapter_type"],
                    is_active=item["is_active"],
                    settings=item["settings"],
                )
            )
        created["suppliers"] = True
        logger.info("Созданы демо-поставщики (%d)", len(DEMO_SUPPLIERS))
        # autoflush=False: flush before the demo_supplier lookup below, so the
        # seeded supplier is visible to the next SELECT.
        db.flush()

    demo_supplier = db.scalars(
        select(Supplier).where(
            Supplier.company_id == company.id,
            Supplier.slug == DEMO_SUPPLIERS[0]["slug"],
        )
    ).first()
    if (
        include_customer_demo
        and demo_supplier is not None
        and _seed_supplier_reliability(db, company, demo_supplier)
    ):
        created["supplier_reliability"] = True
        logger.info("Создана демо-телеметрия надёжности поставщика")

    fitment_catalog_count = db.scalars(
        select(CatalogFitment).where(CatalogFitment.company_id == company.id)
    ).all()
    if not fitment_catalog_count:
        for item in DEMO_CATALOG_FITMENTS:
            db.add(
                CatalogFitment(
                    company_id=company.id,
                    article=item["article"],
                    brand=item["brand"],
                    part_name=item["part_name"],
                    vehicle_brand=item["vehicle_brand"],
                    vehicle_model=item["vehicle_model"],
                    year_from=item["year_from"],
                    year_to=item["year_to"],
                    engine=item["engine"],
                    source=item["source"],
                    oem_article=item["oem_article"],
                    confidence=item["confidence"],
                )
            )
        created["fitment"] = True
        logger.info(
            "Создан демо-каталог совместимости (%d записей)",
            len(DEMO_CATALOG_FITMENTS),
        )
    cross_count = db.scalars(
        select(CrossReference).where(CrossReference.company_id == company.id)
    ).all()
    if not cross_count:
        for item in DEMO_CROSS_REFERENCES:
            db.add(
                CrossReference(
                    company_id=company.id,
                    source_article=item["source_article"],
                    source_brand=item["source_brand"],
                    target_article=item["target_article"],
                    target_brand=item["target_brand"],
                    confidence=item["confidence"],
                    source=item["source"],
                )
            )
        logger.info("Созданы демо-кросс-референсы (%d)", len(DEMO_CROSS_REFERENCES))

    if include_customer_demo and _seed_customer_garage(db, company):
        created["garage"] = True

    admin = db.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    if admin is None:
        # A bootstrap admin is created only when an explicit password is set
        # (SEED_ADMIN_PASSWORD). In production the password is validated at
        # startup; the account must change it on first login. An empty
        # password means "do not auto-create an admin".
        if not settings.seed_admin_password:
            logger.warning(
                "SEED_ADMIN_PASSWORD не задан: администратор %s не создан.",
                settings.seed_admin_email,
            )
        else:
            db.add(
                User(
                    email=settings.seed_admin_email,
                    full_name=settings.seed_admin_name,
                    hashed_password=hash_password(settings.seed_admin_password),
                    is_superuser=True,
                    is_active=True,
                    company_id=company.id,
                    must_change_password=(settings.environment == "production"),
                    role="owner",
                )
            )
            created["admin"] = True
            logger.info(
                "Создан администратор %s (пароль из env: SEED_ADMIN_PASSWORD)",
                settings.seed_admin_email,
            )
    elif admin.company_id is None:
        # Backfill: an admin created before users.company_id existed must be
        # scoped to the demo company, otherwise approval/quote APIs forbid it.
        admin.company_id = company.id

    db.commit()
    return created
