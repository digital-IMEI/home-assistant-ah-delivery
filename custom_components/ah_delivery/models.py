"""Data models and response parsing for Albert Heijn Delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class Delivery:
    """One open AH home delivery."""

    order_id: int | None
    status: str | None
    status_description: str | None
    shopping_type: str
    slot_start: datetime
    slot_end: datetime
    slot_display: str | None
    delivery_date_display: str | None
    eta: datetime | None = None
    eta_lower: datetime | None = None
    eta_upper: datetime | None = None
    eta_status: str | None = None
    eta_observed_at: datetime | None = None

    def best_time(self, now: datetime, eta_max_age_seconds: int = 600) -> tuple[datetime, str]:
        """Return best arrival timestamp and its source."""
        if self.eta is not None and self.eta_observed_at is not None:
            age = (now - self.eta_observed_at).total_seconds()
            if 0 <= age <= eta_max_age_seconds:
                return self.eta, "live_eta"
        return self.slot_start, "delivery_slot"


@dataclass(frozen=True, slots=True)
class DeliveryData:
    """Coordinator payload."""

    deliveries: tuple[Delivery, ...]
    next_delivery: Delivery | None
    fetched_at: datetime
    rich_eta_supported: bool | None


def _parse_clock(value: str) -> time:
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported AH time value: {value!r}")


def _parse_datetime_like(value: Any, tz: ZoneInfo, delivery_date: str | None = None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    # Full ISO-8601 timestamps, including Z or an explicit offset.
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    except ValueError:
        pass
    # Time-only values need the delivery date.
    if delivery_date:
        try:
            d = datetime.strptime(delivery_date, "%Y-%m-%d").date()
            return datetime.combine(d, _parse_clock(raw), tzinfo=tz)
        except ValueError:
            return None
    return None


def parse_fulfillments(payload: dict[str, Any], timezone_name: str, fetched_at: datetime) -> tuple[Delivery, ...]:
    """Parse GraphQL fulfillment data; malformed individual entries are ignored."""
    tz = ZoneInfo(timezone_name)
    root = payload.get("orderFulfillments") if isinstance(payload, dict) else None
    results = root.get("result", []) if isinstance(root, dict) else []
    deliveries: list[Delivery] = []

    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("shoppingType", "")).upper() != "DELIVERY":
            continue
        delivery = item.get("delivery")
        if not isinstance(delivery, dict):
            continue
        slot = delivery.get("slot")
        if not isinstance(slot, dict):
            continue
        date_value = slot.get("date")
        if not isinstance(date_value, str):
            continue
        start = _parse_datetime_like(slot.get("startTime"), tz, date_value)
        end = _parse_datetime_like(slot.get("endTime"), tz, date_value)
        if start is None or end is None:
            continue
        # If AH ever supplies an overnight slot, keep end after start.
        if end < start:
            end += timedelta(days=1)

        eta_raw = delivery.get("eta")
        eta = eta_lower = eta_upper = None
        eta_status = None
        if isinstance(eta_raw, dict):
            eta = _parse_datetime_like(eta_raw.get("estimated"), tz, date_value)
            eta_lower = _parse_datetime_like(eta_raw.get("lower"), tz, date_value)
            eta_upper = _parse_datetime_like(eta_raw.get("upper"), tz, date_value)
            if eta_raw.get("status") is not None:
                eta_status = str(eta_raw.get("status"))

        deliveries.append(
            Delivery(
                order_id=item.get("orderId") if isinstance(item.get("orderId"), int) else None,
                status=str(delivery.get("status")) if delivery.get("status") is not None else None,
                status_description=(
                    str(item.get("statusDescription")) if item.get("statusDescription") is not None else None
                ),
                shopping_type="DELIVERY",
                slot_start=start,
                slot_end=end,
                slot_display=str(slot.get("timeDisplay")) if slot.get("timeDisplay") is not None else None,
                delivery_date_display=(
                    str(slot.get("dateDisplay")) if slot.get("dateDisplay") is not None else None
                ),
                eta=eta,
                eta_lower=eta_lower,
                eta_upper=eta_upper,
                eta_status=eta_status,
                eta_observed_at=fetched_at if eta is not None else None,
            )
        )

    deliveries.sort(key=lambda d: d.slot_start)
    return tuple(deliveries)


def select_next_delivery(deliveries: tuple[Delivery, ...], now: datetime) -> Delivery | None:
    """Select the next relevant delivery.

    A current API response can still report an open order just after its booked
    slot has ended (for example when the driver is late). Keep such an order for
    a short grace period, and extend relevance to a current ETA/ETA upper bound.
    """
    grace = timedelta(hours=2)
    for delivery in deliveries:
        relevant_until = delivery.slot_end + grace
        for candidate in (delivery.eta, delivery.eta_upper):
            if candidate is not None and candidate > relevant_until:
                relevant_until = candidate
        if relevant_until >= now:
            return delivery
    return None
