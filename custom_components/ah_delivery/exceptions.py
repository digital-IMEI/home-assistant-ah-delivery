"""Exceptions for Albert Heijn Delivery."""

from __future__ import annotations


class AhDeliveryError(Exception):
    """Base API error."""


class AhAuthError(AhDeliveryError):
    """Authentication is invalid and user intervention is required."""


class AhTransientError(AhDeliveryError):
    """Temporary communication or server error."""


class AhRequestError(AhDeliveryError):
    """Albert Heijn rejected a non-authentication API request."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class AhRateLimitError(AhTransientError):
    """API rate limit was hit."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AhGraphQLError(AhTransientError):
    """GraphQL returned one or more errors."""
