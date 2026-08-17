from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from app.suppliers.base import (
    ExternalOrderResult,
    NormalizedSupplierOffer,
    SupplierOrderData,
    SupplierSearchQuery,
)
from app.suppliers.errors import (
    SupplierAdapterError,
    SupplierAuthError,
    SupplierParseError,
    SupplierQueryNotSupported,
    SupplierResponseError,
)
from app.suppliers.http import HttpSupplierAdapter


class ArmtekAdapter(HttpSupplierAdapter):
    """Armtek (Armtek.ru) preset — JSON B2B API (Sprint 4.7).

    Registered as ``adapter_type="armtek"``. This class carries the provider
    preset (default endpoints, field keys, order/tracking config) only — the
    behavior lives in :class:`HttpSupplierAdapter`, so connecting Armtek never
    touched the core. Fill in real credentials and adjust the endpoint paths in
    the supplier's ``settings`` (they override ``DEFAULT_SETTINGS``).
    """

    type = "armtek"

    experimental: ClassVar[bool] = True

    DEFAULT_SETTINGS: ClassVar[dict[str, Any]] = {
        "base_url": "https://api.armtek.ru",
        "search_path": "/api/v2/search",
        "auth": {"mode": "api_key", "key_header": "X-Armtek-Api-Key", "value": ""},
        "offers_key": "data.items",
        "crosses_key": "data.crosses",
        "keys": {
            "article": "article",
            "brand": "brand",
            "name": "name",
            "price": "price",
            "quantity": "quantity",
            "delivery_days": "delivery_days",
        },
        "order": {
            "method": "POST",
            "path": "/api/v2/orders",
            "body": {
                "order_number": "{order_number}",
                "delivery_days": "{delivery_days}",
                "items": "{items}",
            },
            "external_order_id": "data.orderId",
            "status": "data.status",
            "estimated_delivery_days": "data.deliveryDays",
            "status_mapping": {
                "new": "accepted",
                "processing": "assembling",
                "shipped": "shipped",
                "delivered": "arrived",
            },
        },
        "status": {
            "method": "GET",
            "path": "/api/v2/orders/{external_order_id}",
            "status": "data.status",
            "status_mapping": {
                "new": "accepted",
                "processing": "assembling",
                "shipped": "shipped",
                "delivered": "arrived",
            },
        },
        "min_interval": 0.3,
        "max_retries": 2,
        "timeout": 10.0,
    }


class ShatemAdapter(HttpSupplierAdapter):
    """Шатэ-М (Shatem.ru) preset — JSON B2B API (Sprint 4.7).

    Registered as ``adapter_type="shatem"``. Thin preset over
    :class:`HttpSupplierAdapter`; operator supplies real API key and endpoints
    via ``settings``.
    """

    type = "shatem"

    experimental: ClassVar[bool] = True

    DEFAULT_SETTINGS: ClassVar[dict[str, Any]] = {
        "base_url": "https://api.shatem.ru",
        "search_path": "/api/v1/search",
        "auth": {"mode": "api_key", "key_header": "X-Shatem-Api-Key", "value": ""},
        "offers_key": "data.offers",
        "crosses_key": "data.crosses",
        "keys": {
            "article": "article",
            "brand": "brand",
            "name": "name",
            "price": "price",
            "quantity": "quantity",
            "delivery_days": "delivery_days",
        },
        "order": {
            "method": "POST",
            "path": "/api/v1/orders",
            "body": {
                "order_number": "{order_number}",
                "items": "{items}",
            },
            "external_order_id": "data.id",
            "status": "data.status",
            "status_mapping": {
                "1": "accepted",
                "2": "assembling",
                "3": "shipped",
                "4": "arrived",
            },
        },
        "status": {
            "method": "GET",
            "path": "/api/v1/orders/{external_order_id}",
            "status": "data.status",
            "status_mapping": {
                "1": "accepted",
                "2": "assembling",
                "3": "shipped",
                "4": "arrived",
            },
        },
        "min_interval": 0.3,
        "max_retries": 2,
        "timeout": 10.0,
    }


class AvtorustAdapter(HttpSupplierAdapter):
    """Авторусь (Avtorust.ru) preset — JSON B2B API (Sprint 4.7).

    Registered as ``adapter_type="avtorust"``. Thin preset over
    :class:`HttpSupplierAdapter`; operator supplies real credentials and
    endpoint paths via ``settings``.
    """

    type = "avtorust"

    experimental: ClassVar[bool] = True

    DEFAULT_SETTINGS: ClassVar[dict[str, Any]] = {
        "base_url": "https://api.avtorust.ru",
        "search_path": "/v2/search",
        "auth": {"mode": "bearer", "token": ""},
        "offers_key": "offers",
        "crosses_key": "analogs",
        "keys": {
            "article": "article",
            "brand": "brand",
            "name": "name",
            "price": "price",
            "quantity": "quantity",
            "delivery_days": "delivery_days",
        },
        "order": {
            "method": "POST",
            "path": "/v2/orders",
            "body": {
                "order": {
                    "number": "{order_number}",
                    "positions": "{items}",
                }
            },
            "external_order_id": "order.id",
            "status": "order.status",
            "estimated_delivery_days": "order.delivery_days",
            "status_mapping": {
                "created": "accepted",
                "collected": "assembling",
                "transferred": "shipped",
                "delivered": "arrived",
            },
        },
        "status": {
            "method": "GET",
            "path": "/v2/orders/{external_order_id}",
            "status": "order.status",
            "status_mapping": {
                "created": "accepted",
                "collected": "assembling",
                "transferred": "shipped",
                "delivered": "arrived",
            },
        },
        "min_interval": 0.3,
        "max_retries": 2,
        "timeout": 10.0,
    }


class AvtokontinentAdapter(HttpSupplierAdapter):
    """Автоконтинент — real JSON B2B API (Sprint 4.7).

    Implements the documented web-service on top of
    :class:`HttpSupplierAdapter` (basic-auth, retry, rate limit reused):

    * **Base URI** — ``http://api.autokontinent.ru/v1/<method>.json``,
      UTF-8, basic authorization.
    * **Search (two steps)** — ``search/part.json?part_code=`` resolves the
      article to cards (``part_id``), then ``search/price.json?part_id=``
      returns stock/price rows per warehouse. Each row becomes an offer;
      rows whose ``part_code`` differs from the requested article are flagged
      ``is_cross=True``. ``delivery_days`` is computed from ``dt_delivery``.
    * **Order** — the supplier orders by basket: ``basket/add.json`` per
      position (part_id + warehouse_id resolved by re-searching the article,
      cheapest in-stock warehouse wins), then ``basket/order.json`` sends the
      basket. The external id is the newest ``order_id`` from ``order/get.json``.
    * **Status** — ``order/get.json`` lists the customer's order lines; the
      state codes map onto the canonical vocabulary (see ``_STATE_MAPPING``).

    Configuration (``settings``)::

        {
            "base_url": "http://api.autokontinent.ru",   # without /v1
            "auth": {"mode": "basic", "username": "...", "password": "..."},
            "max_cards": 10,
            "min_interval": 0.2, "max_retries": 2, "timeout": 8.0,
        }
    """

    type = "avtokontinent"

    experimental: ClassVar[bool] = True

    _API_VERSION = "v1"

    # order/get.json "state" codes -> canonical supplier statuses. Refusals
    # (7, 9, 13) intentionally map to "unknown" so tracking never reports a
    # wrong positive; 14 «Выдан» == delivered.
    _STATE_MAPPING: ClassVar[dict[int, str]] = {
        1: "accepted",    # Принят
        2: "accepted",    # Проверка кредитного лимита
        3: "accepted",    # Заблокирован, требует оплаты
        4: "assembling",  # В работе на складе
        5: "shipped",     # Отгружен
        6: "accepted",    # Отправлен заказ поставщику
        8: "arrived",     # Поступил на склад
        10: "accepted",   # Подтвержден поставщиком
        11: "shipped",    # Отправлен на аутпост
        12: "arrived",    # Прибыл на аутпост
        14: "delivered",  # Выдан
    }

    DEFAULT_SETTINGS: ClassVar[dict[str, Any]] = {
        "base_url": "http://api.autokontinent.ru",
        "auth": {"mode": "basic", "username": "", "password": ""},
        "max_cards": 10,
        "min_interval": 0.2,
        "max_retries": 2,
        "backoff_base": 0.5,
        "timeout": 8.0,
    }

    def __init__(
        self, *, name: str = "", settings: dict[str, Any] | None = None
    ) -> None:
        settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        settings["search_path"] = "/search"  # unused; kept for base contract
        super().__init__(name=name, settings=settings)
        self.max_cards = int(settings.get("max_cards", 10) or 10)

    # --- Public API --------------------------------------------------------

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        article = (query.article or "").strip()
        if not article:
            raise SupplierQueryNotSupported(
                f"Поставщик «{self.name}» ищет только по артикулу."
            )
        cards = await self._api_call("search/part", {"part_code": article})
        if not isinstance(cards, list):
            raise SupplierParseError(
                "Поставщик «Автоконтинент» вернул неожиданную структуру search/part."
            )
        offers: list[NormalizedSupplierOffer] = []
        for card in cards[: self.max_cards]:
            part_id = card.get("part_id")
            if part_id is None:
                continue
            rows = await self._api_call(
                "search/price", {"part_id": part_id, "show_cross": "true"}
            )
            if not isinstance(rows, list):
                continue
            for row in rows:
                offer = self._price_row_to_offer(row, requested=article)
                if offer is not None:
                    offers.append(offer)
        return offers

    async def order(self, *, data: SupplierOrderData) -> ExternalOrderResult:
        if not data.items:
            raise SupplierResponseError(
                f"Поставщик «{self.name}»: нет позиций для заказа."
            )
        for item in data.items:
            article = str(item.get("article") or "").strip()
            quantity = int(item.get("quantity") or 1)
            part_id, warehouse_id = await self._resolve_part(article)
            result = await self._api_call(
                "basket/add",
                {
                    "part_id": part_id,
                    "warehouse_id": warehouse_id,
                    "quantity": quantity,
                },
            )
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise SupplierResponseError(
                    f"Поставщик «{self.name}» не принял позицию {article} в корзину."
                )
        ordered = await self._api_call("basket/order", {"delivery_mode_id": 1})
        if not isinstance(ordered, dict) or ordered.get("status") != "ok":
            raise SupplierResponseError(
                f"Поставщик «{self.name}» не принял корзину в заказ."
            )
        order_id = await self._newest_order_id()
        return ExternalOrderResult(
            external_order_id=order_id,
            status="accepted",
            message=f"Заказ {data.order_number} принят поставщиком «{self.name}».",
        )

    async def order_status(self, external_order_id: str) -> str:
        lines = await self._api_call("order/get", {})
        if not isinstance(lines, list):
            return "unknown"
        states = [
            int(line["state"])
            for line in lines
            if str(line.get("order_id")) == str(external_order_id)
            and line.get("state") is not None
        ]
        if not states:
            return "unknown"
        return self._STATE_MAPPING.get(max(states), "unknown")

    async def healthcheck(self) -> bool:
        try:
            result = await self._api_call("search/part", {"part_code": "P06089"})
            return isinstance(result, list)
        except SupplierAdapterError:
            return False
        except Exception:
            return False

    # --- Autokontinent plumbing -------------------------------------------

    async def _api_call(self, method: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}/{self._API_VERSION}/{method}.json"
        response = await self._request(url, params={str(k): str(v) for k, v in params.items()})
        payload = self._parse_json(response)
        if isinstance(payload, dict) and "error_code" in payload:
            self._raise_error_code(payload)
        return payload

    def _raise_error_code(self, payload: dict[str, Any]) -> None:
        code = payload.get("error_code")
        message = str(payload.get("error_message") or "") or str(code)
        if code == 1:
            raise SupplierAuthError(
                f"Поставщик «{self.name}» отклонил авторизацию: {message}"
            )
        if code in (3, 4):
            raise SupplierResponseError(
                f"Поставщик «{self.name}» отклонил запрос: {message}"
            )
        raise SupplierResponseError(
            f"Поставщик «{self.name}» вернул ошибку: {message}"
        )

    async def _resolve_part(self, article: str) -> tuple[int, int]:
        cards = await self._api_call("search/part", {"part_code": article})
        if not isinstance(cards, list) or not cards:
            raise SupplierResponseError(
                f"Поставщик «{self.name}» не нашёл артикул {article}."
            )
        part_id = int(cards[0]["part_id"])
        rows = await self._api_call("search/price", {"part_id": part_id})
        if not isinstance(rows, list) or not rows:
            raise SupplierResponseError(
                f"Поставщик «{self.name}» не нашёл предложения по {article}."
            )
        best = min(
            rows,
            key=lambda r: (
                self._stock_qty(r) < int(r.get("quantity") or 0),
                self._integer(r.get("price")) is None,
                self._integer(r.get("price")) or 0,
            ),
        )
        return part_id, int(best["warehouse_id"])

    async def _newest_order_id(self) -> str:
        lines = await self._api_call("order/get", {})
        if not isinstance(lines, list):
            return "unknown"
        ids = [int(line["order_id"]) for line in lines if line.get("order_id") is not None]
        if not ids:
            return "unknown"
        return str(max(ids))

    @staticmethod
    def _stock_qty(row: dict[str, Any]) -> int:
        try:
            return int(float(str(row.get("quantity") or "0")))
        except (TypeError, ValueError):
            return 0

    def _price_row_to_offer(
        self, row: dict[str, Any], *, requested: str
    ) -> NormalizedSupplierOffer | None:
        if not isinstance(row, dict):
            return None
        article = str(row.get("part_code") or "").strip()
        if not article:
            return None
        return NormalizedSupplierOffer(
            supplier_name=self.name,
            brand=str(row.get("brand_name") or "").strip() or self.name,
            article=article,
            part_name=str(row.get("part_name") or "").strip(),
            purchase_price=self._decimal(row.get("price")),
            quantity=self._stock_qty(row) or None,
            delivery_days=self._delivery_days(row.get("dt_delivery")),
            is_cross=article != requested,
        )

    @staticmethod
    def _delivery_days(value: Any) -> int | None:
        if not value:
            return None
        text = str(value).strip()
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(text, fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        if dt is None:
            return None
        days = (dt.date() - datetime.now(UTC).date()).days
        return max(days, 1) if days >= 0 else None
