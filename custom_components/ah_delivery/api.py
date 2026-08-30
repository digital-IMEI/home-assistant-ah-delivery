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
    LOGIN_BASE_URL,
    RICH_FULFILLMENTS_QUERY,
    TOKEN_REFRESH_MARGIN,
    USER_AGENT,
)
from .exceptions import AhAuthError, AhGraphQLError, AhRateLimitError, AhTransientError
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

    @property
    def member_id(self) -> str:
        return self._member_id

    @property
    def rich_query_supported(self) -> bool | None:
        return self._rich_query_supported

    @staticmethod
    def login_url() -> str:
        return (
            f"{LOGIN_BASE_URL}/login?client_id={CLIENT_ID}"
            "&response_type=code&redirect_uri=appie%3A%2F%2Flogin-exit"
        )

    @staticmethod
    def extract_authorization_code(value: str) -> str:
        """Accept a raw code, an appie:// redirect, or a normal URL containing code=."""
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
        payload = await self._raw_request(
            "POST",
            "/mobile-auth/v1/auth/token",
            json_body={"clientId": CLIENT_ID, "code": code},
            authenticated=False,
        )
        await self._accept_token_payload(payload)
        return self.token_data()

    async def async_refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise AhAuthError("No refresh token is available")
        async with self._refresh_lock:
            # Another task may have refreshed while we waited.
            if self._token_is_fresh():
                return
            payload = await self._raw_request(
                "POST",
                "/mobile-auth/v1/auth/token/refresh",
                json_body={"clientId": CLIENT_ID, "refreshToken": self._refresh_token},
                authenticated=False,
                allow_refresh=False,
            )
            await self._accept_token_payload(payload)

    def _token_is_fresh(self) -> bool:
        if not self._access_token:
            return False
        if not self._expires_at:
            return True
        return datetime.now(timezone.utc).timestamp() + TOKEN_REFRESH_MARGIN.total_seconds() < self._expires_at

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
            datetime.now(timezone.utc).timestamp() + expires_seconds if expires_seconds else 0
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

        if response.status == 401 and authenticated and allow_refresh and self._refresh_token:
            response.release()
            # Force refresh even if the stored expiry was optimistic.
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
            raise AhAuthError(f"Albert Heijn rejected authentication (HTTP {response.status})")
        if response.status == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                retry_seconds = int(retry_after) if retry_after else None
            except ValueError:
                retry_seconds = None
            raise AhRateLimitError("Albert Heijn rate limit reached", retry_seconds)
        if response.status >= 500:
            raise AhTransientError(f"Albert Heijn server error (HTTP {response.status})")
        if response.status >= 400:
            # Token exchange failures are authentication failures, not transient errors.
            raise AhAuthError(f"Albert Heijn request was rejected (HTTP {response.status})")
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise AhTransientError("Albert Heijn returned invalid JSON") from err
        if not isinstance(data, dict):
            raise AhTransientError("Albert Heijn returned an unexpected response type")
        return data

    async def _graphql(self, query: str) -> dict[str, Any]:
        payload = await self._raw_request(
            "POST", "/graphql", json_body={"query": query, "variables": {}}
        )
        errors = payload.get("errors")
        if errors:
            messages = [str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in errors]
            raise AhGraphQLError("; ".join(messages))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AhTransientError("Albert Heijn GraphQL response has no data object")
        return data

    async def async_get_open_deliveries(self, timezone_name: str, fetched_at: datetime) -> tuple[Delivery, ...]:
        """Return open DELIVERY fulfillments, preferring optional ETA fields when supported."""
        if self._rich_query_supported is not False:
            try:
                data = await self._graphql(RICH_FULFILLMENTS_QUERY)
            except AhGraphQLError as err:
                self._rich_query_supported = False
                _LOGGER.debug("ETA fields are not available; using slot-only query: %s", err)
            else:
                self._rich_query_supported = True
                return parse_fulfillments(data, timezone_name, fetched_at)

        data = await self._graphql(BASE_FULFILLMENTS_QUERY)
        return parse_fulfillments(data, timezone_name, fetched_at)
