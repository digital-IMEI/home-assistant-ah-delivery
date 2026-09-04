"""Async Albert Heijn mobile API client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import (
    API_BASE_URL,
    APPLICATION,
    BASE_FULFILLMENTS_QUERY,
    CLIENT_ID,
    CLIENT_VERSION,
    ETA_PROBE_QUERY,
    LOGIN_BASE_URL,
    RICH_FULFILLMENTS_QUERY,
    RIDE_PROBE_QUERY,
    TOKEN_REFRESH_MARGIN,
    USER_AGENT,
)
from .diagnostic_helpers import merge_fulfillment_payload, sanitize_for_diagnostics
from .exceptions import (
    AhAuthError,
    AhGraphQLError,
    AhRateLimitError,
    AhRequestError,
    AhTransientError,
)
from .models import Delivery, parse_fulfillments

_LOGGER = logging.getLogger(__name__)

TokenUpdateCallback = Callable[[dict[str, Any]], Awaitable[None]]


class AhApiClient:
    """Minimal async client for the unofficial AH mobile API."""

    def __init__(
        self,
        session: ClientSession,
        *,
        access_token: str = "",
        refresh_token: str = "",
        expires_at: float = 0,
        member_id: str = "",
        token_update_callback: TokenUpdateCallback | None = None,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._member_id = member_id
        self._token_update_callback = token_update_callback
        self._base_url = base_url.rstrip("/")
        self._refresh_lock = asyncio.Lock()
        self._rich_query_supported: bool | None = None
        self._detail_argument: str | bool | None = None
        self._diagnostic_snapshot: dict[str, Any] = {}

    @property
    def member_id(self) -> str:
        return self._member_id

    @property
    def rich_query_supported(self) -> bool | None:
        return self._rich_query_supported

    @property
    def diagnostic_snapshot(self) -> dict[str, Any]:
        """Return the latest privacy-safe diagnostic probe snapshot."""
        return self._diagnostic_snapshot

    @staticmethod
    def login_url() -> str:
        return (
            f"{LOGIN_BASE_URL}/login?client_id={CLIENT_ID}"
            "&response_type=code&redirect_uri=appie%3A%2F%2Flogin-exit"
        )

    @staticmethod
    def extract_authorization_code(value: str) -> str:
        raw = value.strip()
        if not raw:
            raise ValueError("Authorization code is empty")
        if "code=" not in raw:
            return raw
        parsed = urlparse(raw)
        code = parse_qs(parsed.query).get("code", [""])[0]
        if not code:
            raise ValueError("No authorization code found in URL")
        return code

    def _headers(self, *, authenticated: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "x-client-name": CLIENT_ID,
            "x-client-version": CLIENT_VERSION,
            "x-application": APPLICATION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if authenticated and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def exchange_authorization_code(self, user_value: str) -> dict[str, Any]:
        code = self.extract_authorization_code(user_value)
        try:
            payload = await self._raw_request(
                "POST",
                "/mobile-auth/v1/auth/token",
                json_body={"clientId": CLIENT_ID, "code": code},
                authenticated=False,
            )
        except AhRequestError as err:
            raise AhAuthError(
                f"Albert Heijn rejected the authorization code: {err}"
            ) from err
        await self._accept_token_payload(payload)
        return self.token_data()

    async def async_refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise AhAuthError("No refresh token is available")
        async with self._refresh_lock:
            if self._token_is_fresh():
                return
            try:
                payload = await self._raw_request(
                    "POST",
                    "/mobile-auth/v1/auth/token/refresh",
                    json_body={"clientId": CLIENT_ID, "refreshToken": self._refresh_token},
                    authenticated=False,
                    allow_refresh=False,
                )
            except AhRequestError as err:
                raise AhAuthError(
                    f"Albert Heijn rejected the refresh token: {err}"
                ) from err
            await self._accept_token_payload(payload)

    def _token_is_fresh(self) -> bool:
        if not self._access_token:
            return False
        if not self._expires_at:
            return True
        return (
            datetime.now(timezone.utc).timestamp()
            + TOKEN_REFRESH_MARGIN.total_seconds()
            < self._expires_at
        )

    async def _ensure_fresh_token(self) -> None:
        if self._token_is_fresh():
            return
        if not self._refresh_token:
            raise AhAuthError("Authentication is missing or expired")
        await self.async_refresh_access_token()

    async def _accept_token_payload(self, payload: dict[str, Any]) -> None:
        access = payload.get("access_token") or payload.get("accessToken")
        refresh = payload.get("refresh_token") or payload.get("refreshToken")
        if not access or not refresh:
            raise AhAuthError("AH token response did not contain usable tokens")
        expires_in = payload.get("expires_in") or payload.get("expiresIn") or 0
        try:
            expires_seconds = max(0, int(expires_in))
        except (TypeError, ValueError):
            expires_seconds = 0
        self._access_token = str(access)
        self._refresh_token = str(refresh)
        self._expires_at = (
            datetime.now(timezone.utc).timestamp() + expires_seconds
            if expires_seconds
            else 0
        )
        member = payload.get("member_id") or payload.get("memberId")
        if member:
            self._member_id = str(member)
        if self._token_update_callback:
            await self._token_update_callback(self.token_data())

    def token_data(self) -> dict[str, Any]:
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
            "member_id": self._member_id,
        }

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        authenticated: bool = True,
        allow_refresh: bool = True,
    ) -> dict[str, Any]:
        if authenticated:
            await self._ensure_fresh_token()

        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(authenticated=authenticated),
                json=json_body,
                timeout=20,
            )
        except (ClientError, TimeoutError, asyncio.TimeoutError) as err:
            raise AhTransientError(f"Could not reach Albert Heijn: {err}") from err

        if (
            response.status == 401
            and authenticated
            and allow_refresh
            and self._refresh_token
        ):
            response.release()
            self._expires_at = 1
            await self.async_refresh_access_token()
            return await self._raw_request(
                method,
                path,
                json_body=json_body,
                authenticated=authenticated,
                allow_refresh=False,
            )

        return await self._decode_response(response)

    async def _decode_response(self, response: ClientResponse) -> dict[str, Any]:
        try:
            text = await response.text()
        finally:
            response.release()
        if response.status in (401, 403):
            raise AhAuthError(
                f"Albert Heijn rejected authentication (HTTP {response.status})"
            )
        if response.status == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                retry_seconds = int(retry_after) if retry_after else None
            except ValueError:
                retry_seconds = None
            raise AhRateLimitError("Albert Heijn rate limit reached", retry_seconds)
        if response.status >= 500:
            raise AhTransientError(
                f"Albert Heijn server error (HTTP {response.status})"
            )
        if response.status >= 400:
            safe_message = f"Albert Heijn request was rejected (HTTP {response.status})"
            if text:
                try:
                    error_payload = json.loads(text)
                except json.JSONDecodeError:
                    error_payload = None
                if isinstance(error_payload, dict):
                    api_code = error_payload.get("code")
                    api_message = error_payload.get("message")
                    details = ": ".join(
                        str(value)
                        for value in (api_code, api_message)
                        if value
                    )
                    if details:
                        safe_message = f"{safe_message}: {details}"
            raise AhRequestError(safe_message, response.status)
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise AhTransientError("Albert Heijn returned invalid JSON") from err
        if not isinstance(data, dict):
            raise AhTransientError(
                "Albert Heijn returned an unexpected response type"
            )
        return data

    async def _graphql(self, query: str) -> dict[str, Any]:
        try:
            payload = await self._raw_request(
                "POST", "/graphql", json_body={"query": query, "variables": {}}
            )
        except AhRequestError as err:
            raise AhGraphQLError(str(err)) from err
        errors = payload.get("errors")
        if errors:
            messages = [
                str(item.get("message", item))
                if isinstance(item, dict)
                else str(item)
                for item in errors
            ]
            raise AhGraphQLError("; ".join(messages))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AhTransientError(
                "Albert Heijn GraphQL response has no data object"
            )
        return data

    async def async_validate_connection(self) -> None:
        await self._graphql(BASE_FULFILLMENTS_QUERY)

    async def _optional_probe(
        self, label: str, query: str, diagnostics: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            data = await self._graphql(query)
        except AhRateLimitError:
            raise
        except AhAuthError:
            raise
        except AhTransientError as err:
            diagnostics["probes"][label] = {"ok": False, "error": str(err)}
            return None
        diagnostics["probes"][label] = {
            "ok": True,
            "data": sanitize_for_diagnostics(data),
        }
        return data

    @staticmethod
    def _first_delivery_order_id(payload: dict[str, Any]) -> int | None:
        root = payload.get("orderFulfillments")
        results = root.get("result", []) if isinstance(root, dict) else []
        for item in results if isinstance(results, list) else []:
            if (
                isinstance(item, dict)
                and str(item.get("shoppingType", "")).upper() == "DELIVERY"
                and isinstance(item.get("orderId"), int)
            ):
                return item["orderId"]
        return None

    @staticmethod
    def _detail_query(order_id: int, argument_name: str) -> str:
        return f"""
query OrderFulfillmentDetailProbe {{
  orderFulfillment({argument_name}: {order_id}) {{
    orderId
    statusCode
    statusDescription
    shoppingType
    transactionCompleted
    modifiable
    cancellable
    reopenable
    closingDateTime
    delivery {{
      status
      method
      deliveryMessage
      shiftCode
      homeShopCenterId
      ride {{
        number
        sequenceNumber
        homeShopCenterId
      }}
      eta {{
        status
        estimated
        lower
        upper
      }}
      slot {{
        date
        dateDisplay
        dateDisplayShort
        timeDisplay
        dayDisplay
        startTime
        endTime
      }}
    }}
  }}
}}
"""

    async def _probe_single_fulfillment(
        self, order_id: int, diagnostics: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self._detail_argument is False:
            diagnostics["probes"]["single_fulfillment"] = {
                "ok": False,
                "error": "argument shape unsupported in this API version",
            }
            return None

        arguments = (
            [self._detail_argument]
            if isinstance(self._detail_argument, str)
            else ["id", "orderId"]
        )
        errors: list[str] = []
        for argument in arguments:
            try:
                data = await self._graphql(self._detail_query(order_id, argument))
            except AhRateLimitError:
                raise
            except AhAuthError:
                raise
            except AhTransientError as err:
                errors.append(f"{argument}: {err}")
                continue
            self._detail_argument = argument
            diagnostics["probes"]["single_fulfillment"] = {
                "ok": True,
                "argument": argument,
                "data": sanitize_for_diagnostics(data),
            }
            result = data.get("orderFulfillment")
            return result if isinstance(result, dict) else None

        self._detail_argument = False
        diagnostics["probes"]["single_fulfillment"] = {
            "ok": False,
            "error": " | ".join(errors) or "no detail data returned",
        }
        return None

    async def async_get_open_deliveries(
        self, timezone_name: str, fetched_at: datetime
    ) -> tuple[Delivery, ...]:
        """Return open DELIVERY fulfillments and capture broad safe diagnostics."""
        diagnostics: dict[str, Any] = {
            "captured_at": fetched_at.isoformat(),
            "client": {
                "client_id": CLIENT_ID,
                "client_version": CLIENT_VERSION,
                "application": APPLICATION,
            },
            "probes": {},
        }

        merged: dict[str, Any]
        rich: dict[str, Any] | None = None
        if self._rich_query_supported is False:
            diagnostics["probes"]["rich_fulfillments"] = {
                "ok": False,
                "skipped": True,
                "error": "previously rejected by this AH API session",
            }
        else:
            try:
                rich = await self._graphql(RICH_FULFILLMENTS_QUERY)
            except AhGraphQLError as err:
                self._rich_query_supported = False
                diagnostics["probes"]["rich_fulfillments"] = {
                    "ok": False,
                    "error": str(err),
                }

        if rich is None:
            base = await self._graphql(BASE_FULFILLMENTS_QUERY)
            diagnostics["probes"]["base_fulfillments"] = {
                "ok": True,
                "data": sanitize_for_diagnostics(base),
            }
            merged = base

            # Probe the single-fulfillment resolver first. If it works, it already
            # carries ETA + ride + message fields and avoids two extra requests.
            order_id = self._first_delivery_order_id(merged)
            detail = (
                await self._probe_single_fulfillment(order_id, diagnostics)
                if order_id is not None
                else None
            )
            if detail is not None:
                wrapped = {"orderFulfillments": {"result": [detail]}}
                merged = merge_fulfillment_payload(merged, wrapped)
            else:
                eta = await self._optional_probe(
                    "eta_only", ETA_PROBE_QUERY, diagnostics
                )
                if eta is not None:
                    merged = merge_fulfillment_payload(merged, eta)

                ride = await self._optional_probe(
                    "ride_and_message", RIDE_PROBE_QUERY, diagnostics
                )
                if ride is not None:
                    merged = merge_fulfillment_payload(merged, ride)
        else:
            self._rich_query_supported = True
            diagnostics["probes"]["rich_fulfillments"] = {
                "ok": True,
                "data": sanitize_for_diagnostics(rich),
            }
            merged = rich

            order_id = self._first_delivery_order_id(merged)
            if order_id is not None:
                detail = await self._probe_single_fulfillment(order_id, diagnostics)
                if detail is not None:
                    wrapped = {"orderFulfillments": {"result": [detail]}}
                    merged = merge_fulfillment_payload(merged, wrapped)

        if self._first_delivery_order_id(merged) is None:
            diagnostics["probes"]["single_fulfillment"] = {
                "ok": False,
                "error": "no open DELIVERY order available",
            }

        diagnostics["merged_fulfillment_data"] = sanitize_for_diagnostics(merged)
        diagnostics["rich_query_supported"] = self._rich_query_supported
        self._diagnostic_snapshot = diagnostics
        return parse_fulfillments(merged, timezone_name, fetched_at)
