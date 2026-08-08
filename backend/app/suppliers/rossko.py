from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.sax.saxutils import escape

import httpx

from app.reliability.circuit_breaker import get_breaker
from app.reliability.errors import FailureKind
from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.errors import (
    SupplierAdapterError,
    SupplierAuthError,
    SupplierConnectionError,
    SupplierParseError,
    SupplierQueryNotSupported,
    SupplierRateLimitError,
    SupplierResponseError,
    SupplierTimeoutError,
)

_RETRIABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_AUTH_HINTS = ("ключ", "авторизац", "key", "credential", "unauthor")
_RATE_HINTS = ("лимит", "limit", "превышен", "too many", "overload")


def _kind_for_status(status: int) -> FailureKind:
    """A retriable HTTP status is an availability signal, not a business error."""
    if status == 429:
        return FailureKind.RATE_LIMITED
    return FailureKind.UNAVAILABLE

_NS_ENVELOPE = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_SERVICE = "https://api.rossko.ru/"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _find_local(el: ET.Element, name: str) -> ET.Element | None:
    for child in el.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(el: ET.Element, name: str, default: str = "") -> str:
    node = _find_local(el, name)
    if node is None or node.text is None:
        return default
    return node.text.strip()


class _Stock:
    __slots__ = ("price", "count", "delivery")

    def __init__(self, price: Decimal | None, count: int | None, delivery: int | None) -> None:
        self.price = price
        self.count = count
        self.delivery = delivery


class _Part:
    __slots__ = ("brand", "partnumber", "name", "stocks", "crosses")

    def __init__(
        self,
        brand: str,
        partnumber: str,
        name: str,
        stocks: list[_Stock],
        crosses: list[ET.Element],
    ) -> None:
        self.brand = brand
        self.partnumber = partnumber
        self.name = name
        self.stocks = stocks
        self.crosses = crosses


class RosskoAdapter(SupplierAdapter):
    """Real Rossko B2B API integration (SOAP 1.1 over HTTPS).

    Implements the platform's ``SupplierAdapter`` contract on top of the
    documented Rossko web service ``GetSearch``
    (https://api.rossko.ru/service/v2.1/GetSearch):

    * **Auth** — ``KEY1``/``KEY2`` (из личного кабинета Rossko) передаются в
      теле SOAP-запроса; неверные ключи дают ``success=false`` → поднимается
      :class:`SupplierAuthError`.
    * **Search** — поисковая строка ``text`` = ``brand + article`` (Rossko ищет
      по артикулу; бренд сужает выдачу, ограниченную 80 карточками).
    * **Stock / price / lead** — у каждой карточки список ``stocks``
      (склад, цена, остаток, дни доставки); выбирается лучший в наличии
      (минимальная цена среди складов с остатком, при равенстве — ближайший
      срок). ``delivery_id`` обязателен, ``address_id`` опционален.
    * **Crosses** — аналоги карточки (``crosses/Part``) расширяются в
      отдельные офферы ``is_cross=True``.
    * **Errors** — ``success=false`` с ``message`` разбирается в типизированные
      ошибки; SOAP Fault тоже нормализуется.
    * **Retry / rate limit** — экспоненциальный бэкoff для транзиентных
      (408/425/429/5xx), учёт ``Retry-After``, мин. интервал между запросами
      (лимит Rossko: 300 поисков/мин).

    Конфигурация (``settings``)::

        {
            "base_url": "https://api.rossko.ru",
            "service_path": "/service/v2.1/GetSearch",
            "key1": "...", "key2": "...",
            "delivery_id": "000000002",
            "address_id": 112233,          # optional
            "max_offers": 20, "max_crosses": 10,
            "min_interval": 0.2, "max_retries": 2, "timeout": 8.0,
        }
    """

    type = "rossko"

    def __init__(
        self, *, name: str = "", settings: dict[str, Any] | None = None
    ) -> None:
        super().__init__(name=name, settings=settings)
        cfg = self.settings
        base_url = str(cfg.get("base_url", "") or "").rstrip("/")
        if not base_url:
            raise ValueError("RosskoAdapter: параметр base_url обязателен")
        self.base_url = base_url
        path = str(cfg.get("service_path") or "/service/v2.1/GetSearch")
        self.service_url = base_url + (path if path.startswith("/") else "/" + path)
        self.key1 = str(cfg.get("key1", "") or "")
        self.key2 = str(cfg.get("key2", "") or "")
        self.delivery_id = str(cfg.get("delivery_id", "") or "")
        if not self.key1 or not self.key2:
            raise ValueError("RosskoAdapter: обязательны key1 и key2")
        self.address_id = cfg.get("address_id")
        self.max_offers = int(cfg.get("max_offers", 20) or 20)
        self.max_crosses = int(cfg.get("max_crosses", 10) or 10)
        self.min_interval = float(cfg.get("min_interval", 0.2) or 0.2)
        self.max_retries = int(cfg.get("max_retries", 2) or 0)
        self.backoff_base = float(cfg.get("backoff_base", 0.5) or 0.5)
        self.timeout = float(cfg.get("timeout", 8.0) or 8.0)
        self.verify = bool(cfg.get("verify", True))
        self._next_request_at = 0.0
        self.requests_made = 0
        self.last_statuses: list[int] = []
        # Unified RetryPolicy (sprint 3.5): transient-only retries with
        # exponential backoff + jitter. Per-supplier config stays authoritative
        # (max_retries / backoff_base from the supplier record).
        from app.reliability.retry import RetryPolicy

        self.retry_policy = RetryPolicy(
            max_attempts=self.max_retries + 1,
            initial_delay=self.backoff_base,
            max_delay=30.0,
        )

    # --- Public API --------------------------------------------------------

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        text = " ".join(filter(None, [query.brand.strip(), query.article.strip()])).strip()
        if not text:
            # Rossko searches keywords over part numbers AND product names, so a
            # free-text query like "масло NGN 5W30 Profi" works without an article.
            text = query.part_name.strip()
        if not text:
            raise SupplierQueryNotSupported(
                f"Поставщик «{self.name}» не получил ни артикула, ни текста запроса."
            )
        params: dict[str, str] = {
            "KEY1": self.key1,
            "KEY2": self.key2,
            "text": text,
            "delivery_id": self.delivery_id,
        }
        if self.address_id is not None:
            params["address_id"] = str(self.address_id)

        result = await self._soap_call("GetSearch", params)
        if not result.success:
            self._raise_business_error(result, status=result.status)

        offers: list[NormalizedSupplierOffer] = []
        for part in result.parts[: self.max_offers]:
            if not part.stocks:
                continue  # карточка без остатков и цен не котируется
            offers.append(self._part_to_offer(part, is_cross=False))
        cross_count = 0
        for part in result.parts[: self.max_offers]:
            for cross in part.crosses:
                if cross_count >= self.max_crosses:
                    break
                if not cross.stocks:
                    continue
                offers.append(self._part_to_offer(cross, is_cross=True))
                cross_count += 1
        return offers

    async def healthcheck(self) -> bool:
        try:
            params = {
                "KEY1": self.key1,
                "KEY2": self.key2,
                "text": "P06089",
                "delivery_id": self.delivery_id,
            }
            if self.address_id is not None:
                params["address_id"] = str(self.address_id)
            result = await self._soap_call("GetSearch", params)
            return bool(result)  # structured SOAP answer => endpoint reachable
        except SupplierAdapterError:
            return False
        except Exception:  # noqa: BLE001 - healthcheck is best-effort
            return False

    # --- SOAP plumbing -----------------------------------------------------

    def _rate_lock_ref(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = getattr(self, f"_lock_{id(loop)}", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(self, f"_lock_{id(loop)}", lock)
        return lock

    async def _throttle(self) -> None:
        async with self._rate_lock_ref():
            now = time.monotonic()
            wait = self._next_request_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_request_at = time.monotonic() + self.min_interval

    def _envelope(self, method: str, params: dict[str, str]) -> str:
        inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in params.items())
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<soap:Envelope xmlns:soap="{_NS_ENVELOPE}">'
            f"<soap:Body>"
            f'<{method} xmlns="{_NS_SERVICE}">{inner}</{method}>'
            f"</soap:Body>"
            f"</soap:Envelope>"
        )

    def _soap_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": self.service_url,
        }

    async def _soap_call(
        self, method: str, params: dict[str, str]
    ) -> "_RosskoResult":
        body = self._envelope(method, params)
        # Circuit breaker "rossko": when open, fail fast instead of waiting
        # for a timeout on a provider we already know is down.
        breaker = get_breaker("rossko")
        if not breaker.allow_request():
            raise SupplierConnectionError(
                f"Поставщик «{self.name}» недоступен: circuit breaker открыт."
            )
        policy = self.retry_policy
        attempt = 0
        while True:
            await self._throttle()
            try:
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
                    response = await client.post(
                        self.service_url, headers=self._soap_headers(), content=body
                    )
            except httpx.TimeoutException as exc:
                if policy.should_retry(FailureKind.TIMEOUT, attempt + 1):
                    attempt += 1
                    await asyncio.sleep(policy.next_delay(attempt))
                    continue
                breaker.record_failure()
                raise SupplierTimeoutError(
                    f"Поставщик «{self.name}» не ответил в течение {self.timeout:g} с."
                ) from exc
            except httpx.HTTPError as exc:
                if policy.should_retry(FailureKind.UNAVAILABLE, attempt + 1):
                    attempt += 1
                    await asyncio.sleep(policy.next_delay(attempt))
                    continue
                breaker.record_failure()
                raise SupplierConnectionError(
                    f"Поставщик «{self.name}» недоступен: {exc.__class__.__name__}"
                ) from exc

            self.requests_made += 1
            self.last_statuses.append(response.status_code)
            try:
                result = self._parse(response)
            except SupplierParseError:
                if (
                    response.status_code in _RETRIABLE_STATUSES
                    and policy.should_retry(_kind_for_status(response.status_code), attempt + 1)
                ):
                    attempt += 1
                    await asyncio.sleep(policy.next_delay(attempt))
                    continue
                raise
            result.status = response.status_code
            if result.success:
                breaker.record_success()
                return result
            if result.kind == "auth" or result.kind == "rate_limit":
                return result
            if (
                response.status_code in _RETRIABLE_STATUSES
                and policy.should_retry(_kind_for_status(response.status_code), attempt + 1)
            ):
                attempt += 1
                await asyncio.sleep(
                    self._retry_after(response) or policy.next_delay(attempt)
                )
                continue
            if response.status_code >= 500:
                breaker.record_failure()
            return result

    def _parse(self, response: httpx.Response) -> "_RosskoResult":
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise SupplierParseError("Поставщик вернул некорректный XML.") from exc

        result_el = _find_local(root, "SearchResult")
        if result_el is None:
            fault = _find_local(root, "faultstring")
            message = fault.text.strip() if fault is not None and fault.text else ""
            return _RosskoResult(
                success=False,
                kind="response",
                message=message or "SOAP-ошибка сервиса Rossko.",
                parts=[],
                status=response.status_code,
            )
        success = _text(result_el, "success") == "true"
        message = _text(result_el, "message")
        kind = self._classify(message)
        parts = self._parse_parts(_find_local(result_el, "PartsList")) if success else []
        return _RosskoResult(success=success, kind=kind, message=message, parts=parts, status=response.status_code)

    @staticmethod
    def _parse_parts(parts_list: ET.Element | None) -> list[_Part]:
        parts: list[_Part] = []
        if parts_list is None:
            return parts
        for part_el in _direct(parts_list, "Part"):
            crosses_el = _find_local(part_el, "crosses")
            crosses = [
                RosskoAdapter._parse_part(cross_el)
                for cross_el in (_direct(crosses_el, "Part") if crosses_el is not None else [])
            ]
            parts.append(RosskoAdapter._parse_part(part_el, crosses=crosses))
        return parts

    @staticmethod
    def _parse_part(part_el: ET.Element, crosses: list["_Part"] | None = None) -> _Part:
        stock_list = _direct(part_el, "stocks")
        stock_elts = _direct(stock_list[0], "stock") if stock_list else []
        stocks = [
            _Stock(
                price=RosskoAdapter._decimal(_text(stock, "price")),
                count=RosskoAdapter._int(_text(stock, "count")),
                delivery=RosskoAdapter._int(_text(stock, "delivery")),
            )
            for stock in stock_elts
        ]
        return _Part(
            brand=_text(part_el, "brand"),
            partnumber=_text(part_el, "partnumber"),
            name=_text(part_el, "name"),
            stocks=stocks,
            crosses=crosses or [],
        )

    @staticmethod
    def _classify(message: str) -> str:
        lower = message.lower()
        if any(hint in lower for hint in _RATE_HINTS):
            return "rate_limit"
        if any(hint in lower for hint in _AUTH_HINTS):
            return "auth"
        return "response"

    def _raise_business_error(self, result: "_RosskoResult", *, status: int) -> None:
        message = result.message or f"Ошибка сервиса Rossko (HTTP {status})."
        if result.kind == "auth":
            raise SupplierAuthError(
                f"Поставщик «{self.name}» отклонил ключи доступа: {message}"
            )
        if result.kind == "rate_limit":
            raise SupplierRateLimitError(
                f"Поставщик «{self.name}» достиг лимита запросов: {message}"
            )
        raise SupplierResponseError(
            f"Поставщик «{self.name}» вернул ошибку: {message}"
        )

    # --- Normalization -----------------------------------------------------

    def _part_to_offer(self, part: _Part, *, is_cross: bool) -> NormalizedSupplierOffer:
        stock = self._best_stock(part.stocks)
        return NormalizedSupplierOffer(
            supplier_name=self.name,
            brand=part.brand.strip() or self.name,
            article=part.partnumber.strip(),
            part_name=part.name.strip(),
            purchase_price=stock.price if stock else None,
            quantity=stock.count if stock else None,
            delivery_days=stock.delivery if stock else None,
            is_cross=is_cross,
        )

    @staticmethod
    def _best_stock(stocks: list[_Stock]) -> _Stock | None:
        in_stock = [s for s in stocks if s.count is not None and s.count > 0]
        pool = in_stock or stocks
        if not pool:
            return None
        return min(
            pool,
            key=lambda s: (
                s.price is None,
                s.price or Decimal("0"),
                s.delivery if s.delivery is not None else 10 ** 9,
            ),
        )

    @staticmethod
    def _decimal(value: str) -> Decimal | None:
        if not value:
            return None
        try:
            return Decimal(value.replace(",", ".").replace(" ", ""))
        except InvalidOperation:
            return None

    @staticmethod
    def _int(value: str) -> int | None:
        if not value:
            return None
        try:
            return int(float(value.replace(",", ".").replace(" ", "")))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class _RosskoResult:
    __slots__ = ("success", "kind", "message", "parts", "status")

    def __init__(
        self,
        *,
        success: bool,
        kind: str,
        message: str,
        parts: list[_Part],
        status: int,
    ) -> None:
        self.success = success
        self.kind = kind
        self.message = message
        self.parts = parts
        self.status = status
