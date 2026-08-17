from __future__ import annotations

import asyncio
import base64
import time
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from app.suppliers.base import (
    ExternalOrderResult,
    NormalizedSupplierOffer,
    SupplierAdapter,
    SupplierOrderData,
    SupplierSearchQuery,
)
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

# Canonical supplier-side statuses (Sprint 4.6 tracking). Providers map their
# own vocabulary onto these via ``status_mapping``.
_CANONICAL_STATUSES = {"accepted", "assembling", "shipped", "arrived", "delivered"}


class HttpSupplierAdapter(SupplierAdapter):
    """Real HTTP supplier integration (Rossko/Armtek-style JSON APIs).

    The adapter speaks the platform contract on the outside (``search`` returns
    normalized offers, ``order`` places a purchase, ``order_status`` polls it)
    and handles the provider's HTTP API on the inside. Everything is
    config-driven: connecting a new provider is a matter of settings (or a thin
    preset subclass) — never a core change.

    * **Auth** — ``api_key`` (custom header), ``bearer`` token or ``basic``
      login/password. 401/403 raise :class:`SupplierAuthError`.
    * **Search** — GET on ``search_path`` with ``article``/``brand`` params.
    * **Crosses** — analogs from ``crosses_key`` are expanded into additional
      offers flagged ``is_cross=True``.
    * **Stock / price / lead time** — ``quantity``, ``price`` and
      ``delivery_days`` mapped through configurable field keys.
    * **Orders (Sprint 4.7)** — ``order`` block: POST on ``order.path`` with an
      optional JSON ``order.body`` template; the external order id, initial
      status and estimated lead are read from dotted paths
      (``order.external_order_id`` / ``order.status`` /
      ``order.estimated_delivery_days``) and mapped onto the canonical
      supplier statuses via ``order.status_mapping``.
    * **Tracking (Sprint 4.7)** — ``status`` block: GET on ``status.path`` with
      the ``{external_order_id}`` placeholder; the status field is read from
      ``status.status`` and mapped via ``status.status_mapping``. Providers
      that only search omit the ``order``/``status`` blocks entirely.
    * **Errors** — every failure is normalized to a typed
      :class:`SupplierAdapterError` with a Russian ``message``.
    * **Retry** — transient failures (network, 408/425/429/5xx) are retried
      with exponential backoff (``max_retries`` attempts).
    * **Rate limit** — a minimum interval between requests
      (``min_interval``) throttles outbound calls; 429 honors ``Retry-After``.

    Configuration (``settings``)::

        {
            "base_url": "https://api.provider.ru",
            "search_path": "/search",
            "auth": {"mode": "api_key", "key_header": "X-Api-Key", "value": "..."},
            # or {"mode": "bearer", "token": "..."} | {"mode": "basic", "username": "...", "password": "..."}
            "offers_key": "data.offers",    # dotted path to offers list
            "crosses_key": "data.crosses",  # dotted path to analog articles (optional)
            "order": {
                "method": "POST",
                "path": "/orders",
                "body": {"order_number": "{order_number}", "items": "{items}"},  # optional template
                "external_order_id": "data.orderId",
                "status": "data.status",
                "estimated_delivery_days": "data.deliveryDays",
                "status_mapping": {"new": "accepted", "processing": "assembling",
                                   "shipped": "shipped", "delivered": "arrived"},
            },
            "status": {
                "method": "GET",
                "path": "/orders/{external_order_id}",
                "status": "data.status",
                "status_mapping": {"new": "accepted", "processing": "assembling",
                                   "shipped": "shipped", "delivered": "arrived"},
            },
            "min_interval": 0.2,
            "max_retries": 2,
            "backoff_base": 0.5,
            "timeout": 8.0,
            "keys": {"article": "article", "brand": "brand", "name": "name",
                     "price": "price", "quantity": "quantity", "delivery_days": "delivery_days"},
        }

    A provider preset is a subclass that sets ``type`` and ``DEFAULT_SETTINGS``
    only — the behavior comes from this class, so connecting Armtek, Шатэ-М,
    Авторусь or Автоконтинент never touches the core.
    """

    type = "http"

    DEFAULT_SETTINGS: ClassVar[dict[str, Any]] = {}

    _DEFAULT_KEYS: ClassVar[dict[str, str]] = {
        "article": "article",
        "brand": "brand",
        "name": "name",
        "price": "price",
        "quantity": "quantity",
        "delivery_days": "delivery_days",
    }

    def __init__(
        self, *, name: str = "", settings: dict[str, Any] | None = None
    ) -> None:
        settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        super().__init__(name=name, settings=settings)
        cfg = self.settings
        base_url = str(cfg.get("base_url", "") or "").rstrip("/")
        if not base_url:
            raise ValueError("HttpSupplierAdapter: параметр base_url обязателен")
        self.base_url = base_url
        self.search_path = self._path(cfg.get("search_path"), "/search")
        self.healthcheck_path = cfg.get("healthcheck_path")
        self.auth = cfg.get("auth") or {}
        self.offers_key = str(cfg.get("offers_key") or "data.offers")
        self.crosses_key = cfg.get("crosses_key")
        self.min_interval = float(cfg.get("min_interval", 0.2) or 0.2)
        self.max_retries = int(cfg.get("max_retries", 2) or 0)
        self.backoff_base = float(cfg.get("backoff_base", 0.5) or 0.5)
        self.timeout = float(cfg.get("timeout", 8.0) or 8.0)
        self.verify = bool(cfg.get("verify", True))
        self._keys = {**self._DEFAULT_KEYS, **(cfg.get("keys") or {})}
        # Sprint 4.7 — order placement / tracking config (optional blocks).
        self.order_cfg = cfg.get("order") or {}
        self.status_cfg = cfg.get("status") or {}
        # Rate limiting state (shared across calls, per adapter instance).
        self._next_request_at = 0.0
        self.requests_made = 0
        self.last_statuses: list[int] = []

    # --- Public API --------------------------------------------------------

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        params = {"article": query.article}
        if query.brand:
            params["brand"] = query.brand
        if query.part_name:
            params["part_name"] = query.part_name
        if query.quantity and query.quantity > 1:
            params["quantity"] = str(query.quantity)

        response = await self._request(self.base_url + self.search_path, params=params)
        payload = self._parse_json(response)

        offers = self._extract(payload, self.offers_key, is_cross=False)
        crosses: list[NormalizedSupplierOffer] = []
        if self.crosses_key:
            crosses = self._extract(payload, self.crosses_key, is_cross=True)
        return offers + crosses

    async def order(self, *, data: SupplierOrderData) -> ExternalOrderResult:
        """Place a purchase with the provider (Sprint 4.7).

        Driven by the ``order`` settings block; providers without it raise
        :class:`SupplierQueryNotSupported` (search-only providers are skipped,
        never crashed on — same contract as the base adapter).
        """
        cfg = self.order_cfg
        path = str(cfg.get("path") or "").strip()
        if not path:
            raise SupplierQueryNotSupported(
                f"Поставщик «{self.name}» не настроен на размещение заказов."
            )
        method = str(cfg.get("method") or "POST").upper()
        body = self._build_order_body(data, cfg.get("body"))
        url = self.base_url + self._path(path, "/orders")
        response = await self._request(
            url, method=method, json_body=body if body else None
        )
        payload = self._parse_json(response)

        external_id = self._get_path(
            payload, str(cfg.get("external_order_id") or "data.orderId")
        )
        if external_id is None:
            raise SupplierParseError(
                f"Поставщик «{self.name}» не вернул идентификатор заказа."
            )
        status = self._map_status(
            self._get_path(payload, str(cfg.get("status") or "")),
            cfg.get("status_mapping"),
            default="accepted",
        )
        estimated_days = self._integer(
            self._get_path(payload, str(cfg.get("estimated_delivery_days") or ""))
        )
        message = self._get_path(payload, str(cfg.get("message") or "")) or ""
        return ExternalOrderResult(
            external_order_id=str(external_id),
            status=status,
            estimated_delivery_days=estimated_days,
            message=str(message),
        )

    async def order_status(self, external_order_id: str) -> str:
        """Poll the provider-side status of a placed order (Sprint 4.7).

        Driven by the ``status`` settings block; the path may contain the
        ``{external_order_id}`` placeholder. Providers without it raise
        :class:`SupplierQueryNotSupported` — tracking is skipped, not broken.
        """
        cfg = self.status_cfg
        path = str(cfg.get("path") or "").strip()
        if not path:
            raise SupplierQueryNotSupported(
                f"Поставщик «{self.name}» не поддерживает отслеживание заказов."
            )
        method = str(cfg.get("method") or "GET").upper()
        url = (
            self.base_url
            + self._path(path, "/orders/{external_order_id}").replace(
                "{external_order_id}", external_order_id
            )
        )
        response = await self._request(url, method=method)
        payload = self._parse_json(response)
        return self._map_status(
            self._get_path(payload, str(cfg.get("status") or "")),
            cfg.get("status_mapping"),
            default="unknown",
        )

    async def healthcheck(self) -> bool:
        url = self.base_url
        if self.healthcheck_path:
            url = url + self._path(self.healthcheck_path)
        try:
            response = await self._request(url)
            return response.status_code < 400
        except SupplierAdapterError:
            return False
        except Exception:
            return False

    # --- HTTP plumbing -----------------------------------------------------

    def _rate_lock_ref(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        # httpx clients are loop-affine; a fresh lock per loop avoids sharing.
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

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        method: str = "GET",
        json_body: Any = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            await self._throttle()
            try:
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=self._auth_headers(),
                    )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await self._sleep_backoff(attempt)
                    continue
                raise SupplierTimeoutError(
                    f"Поставщик «{self.name}» не ответил в течение {self.timeout:g} с."
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await self._sleep_backoff(attempt)
                    continue
                raise SupplierConnectionError(
                    f"Поставщик «{self.name}» недоступен: {exc.__class__.__name__}"
                ) from exc

            self.requests_made += 1
            self.last_statuses.append(response.status_code)
            status = response.status_code

            if status in (401, 403):
                raise SupplierAuthError(
                    f"Поставщик «{self.name}» отклонил авторизацию (HTTP {status}). "
                    "Проверьте ключ доступа в настройках поставщика."
                )
            if status == 429:
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self._retry_after(response) or self._backoff(attempt))
                    continue
                raise SupplierRateLimitError(
                    f"Поставщик «{self.name}» исчерпал лимит запросов (HTTP 429)."
                )
            if status in _RETRIABLE_STATUSES and attempt < self.max_retries:
                attempt += 1
                await self._sleep_backoff(attempt)
                continue
            if status >= 400:
                raise SupplierResponseError(
                    f"Поставщик «{self.name}» вернул ошибку HTTP {status}."
                )
            return response

    def _auth_headers(self) -> dict[str, str]:
        mode = (self.auth.get("mode") or "").lower()
        if mode == "api_key":
            header = str(self.auth.get("key_header") or "X-Api-Key")
            return {header: str(self.auth.get("value") or "")}
        if mode == "bearer":
            return {"Authorization": f"Bearer {self.auth.get('token', '')}"}
        if mode == "basic":
            raw = f"{self.auth.get('username', '')}:{self.auth.get('password', '')}"
            token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}
        return {}

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _backoff(self, attempt: int) -> float:
        return min(self.backoff_base * (2 ** (attempt - 1)), 30.0)

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._backoff(attempt))

    # --- Payload parsing ---------------------------------------------------

    def _build_order_body(
        self, data: SupplierOrderData, template: Any
    ) -> dict[str, Any] | None:
        """Build the order request body from the purchase data.

        A JSON template (``order.body``) may use the ``{order_number}``,
        ``{delivery_days}`` and ``{items}`` placeholders; without a template a
        sensible default body is produced.
        """
        items = [
            {
                "article": str(it.get("article") or ""),
                "brand": str(it.get("brand") or ""),
                "part_name": str(it.get("part_name") or ""),
                "quantity": it.get("quantity"),
                "purchase_price": (
                    str(it.get("purchase_price")) if it.get("purchase_price") is not None else None
                ),
            }
            for it in data.items
        ]
        if template is None:
            return {
                "order_number": data.order_number,
                "items": items,
                "delivery_days": data.delivery_days,
            }
        return self._render_template(
            template,
            values={
                "order_number": data.order_number,
                "items": items,
                "delivery_days": data.delivery_days,
            },
        )

    @classmethod
    def _render_template(cls, node: Any, values: dict[str, Any]) -> Any:
        if isinstance(node, dict):
            return {key: cls._render_template(val, values) for key, val in node.items()}
        if isinstance(node, list):
            return [cls._render_template(val, values) for val in node]
        if isinstance(node, str):
            # A lone placeholder is substituted with the object itself (e.g.
            # "{items}" -> the positions list), not its repr.
            if node.startswith("{") and node.endswith("}") and node[1:-1] in values:
                return values[node[1:-1]]
            return node.format(**values)
        return node

    def _map_status(
        self,
        raw: Any,
        mapping: dict[str, Any] | None,
        *,
        default: str,
    ) -> str:
        """Map a provider status onto the canonical supplier vocabulary.

        Provider values may be passed through as-is when they already match the
        canonical set; ``status_mapping`` (provider -> canonical) overrides;
        otherwise the ``default`` is used so unknown values never crash
        tracking.
        """
        if raw is None or raw == "":
            return default
        value = str(raw).strip()
        lower = value.lower()
        if lower in _CANONICAL_STATUSES:
            return lower
        if mapping:
            mapped = mapping.get(value) or mapping.get(lower)
            if mapped:
                return str(mapped)
        return default

    @staticmethod
    def _parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError, TypeError) as exc:
            raise SupplierParseError(
                "Поставщик вернул некорректный JSON."
            ) from exc

    def _extract(
        self, payload: Any, key_path: str, *, is_cross: bool
    ) -> list[NormalizedSupplierOffer]:
        if not isinstance(payload, (dict, list)):
            raise SupplierParseError("Поставщик вернул неожиданную структуру данных.")
        items = self._get_path(payload, key_path)
        if items is None:
            return []
        if not isinstance(items, list):
            raise SupplierParseError(f"Поле «{key_path}» должно быть списком.")
        offers = [self._normalize(item, is_cross=is_cross) for item in items]
        return [o for o in offers if o is not None]

    @staticmethod
    def _get_path(payload: Any, key_path: str) -> Any:
        current = payload
        for part in key_path.split("."):
            if not part:
                continue
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _normalize(self, item: Any, *, is_cross: bool) -> NormalizedSupplierOffer | None:
        if not isinstance(item, dict):
            raise SupplierParseError("Запись оффера должна быть объектом.")
        article = str(item.get(self._keys["article"], "") or "").strip()
        if not article:
            raise SupplierParseError("Запись оффера не содержит артикула.")
        return NormalizedSupplierOffer(
            supplier_name=self.name,
            brand=str(item.get(self._keys["brand"], "") or "").strip() or self.name,
            article=article,
            part_name=str(item.get(self._keys["name"], "") or "").strip(),
            purchase_price=self._decimal(item.get(self._keys["price"])),
            quantity=self._integer(item.get(self._keys["quantity"])),
            delivery_days=self._integer(item.get(self._keys["delivery_days"])),
            is_cross=is_cross,
        )

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float, Decimal)):
            text = str(value)
        else:
            text = str(value).strip().replace(",", ".").replace(" ", "")
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    @staticmethod
    def _integer(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(str(value).replace(",", ".").replace(" ", "")))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _path(value: Any, default: str) -> str:
        if not value:
            return default
        text = str(value)
        return text if text.startswith("/") else "/" + text
