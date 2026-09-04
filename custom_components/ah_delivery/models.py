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
    status_code: int | None
    shopping_type: str
    transaction_completed: bool | None
    modifiable: bool | None
    cancellable: bool | None
    reopenable: bool | None
    closing_date_time: str | None
    slot_start: datetime
    slot_end: datetime
    slot_display: str | None
    delivery_date_display: str | None
    delivery_date_display_short: str | None = None
    delivery_day_display: str | None = None
    delivery_method: str | None = None
    delivery_message: str | None = None
    shift_code: str | None = None
    home_shop_center_id: int | None = None
    ride_number: int | None = None
    ride_sequence_number: int | None = None
    ride_home_shop_center_id: int | None = None
    eta: datetime | None = None
    eta_lower: datetime | None = None
    eta_upper: datetime | None = None
    eta_status: str | None = None
    eta_observed_at: datetime | None = None

    def best_time(self, now: datetime, eta_max_age_seconds: int = 900) -> tuple[datetime, str]:
        """Return best single arrival timestamp and its source."""
        if self.eta is not None and self.eta_is_fresh(now, eta_max_age_seconds):
            return self.eta, "live_eta"
        return self.slot_start, "delivery_slot"

    def eta_is_fresh(self, now: datetime, eta_max_age_seconds: int = 900) -> bool:
        """Whether any observed ETA data is still fresh."""
        if self.eta_observed_at is None:
            return False
        age = (now - self.eta_observed_at).total_seconds()
        return 0 <= age <= eta_max_age_seconds

    def eta_window(
        self, now: datetime, eta_max_age_seconds: int = 900
    ) -> tuple[datetime | None, datetime | None] | None:
        """Return a fresh ETA lower/upper window if AH supplied one."""
        if not self.eta_is_fresh(now, eta_max_age_seconds):
            return None
        if self.eta_lower is None and self.eta_upper is None:
            return None
        return self.eta_lower, self.eta_upper


@dataclass(frozen=True, slots=True)
class DeliveryData:
    """Coordinator payload."""

    deliveries: tuple[Delivery, ...]
    next_delivery: Delivery | None
    fetched_at: datetime
    rich_eta_supported: bool | None
    diagnostics: dict[str, Any]


def _parse_clock(value: str) -> time:
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported AH time value: {value!r}")


def _parse_datetime_like(
    value: Any, tz: ZoneInfo, delivery_date: str | None = None
) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    except ValueError:
        pass
    if delivery_date:
        try:
            d = datetime.strptime(delivery_date, "%Y-%m-%d").date()
            return datetime.combine(d, _parse_clock(raw), tzinfo=tz)
        except ValueError:
            return None
    return None


def _as_optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _as_optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def parse_fulfillments(
    payload: dict[str, Any], timezone_name: str, fetched_at: datetime
) -> tuple[Delivery, ...]:
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
        if end < start:
            end += timedelta(days=1)

        eta_raw = delivery.get("eta")
        eta = eta_lower = eta_upper = None
        eta_status = None
        if isinstance(eta_raw, dict):
            eta = _parse_datetime_like(eta_raw.get("estimated"), tz, date_value)
            eta_lower = _parse_datetime_like(eta_raw.get("lower"), tz, date_value)
            eta_upper = _parse_datetime_like(eta_raw.get("upper"), tz, date_value)
            eta_status = _as_optional_str(eta_raw.get("status"))

        ride_raw = delivery.get("ride")
        ride = ride_raw if isinstance(ride_raw, dict) else {}
        eta_observed = fetched_at if any((eta, eta_lower, eta_upper, eta_status)) else None

        deliveries.append(
            Delivery(
                order_id=_as_optional_int(item.get("orderId")),
                status=_as_optional_str(delivery.get("status")),
                status_description=_as_optional_str(item.get("statusDescription")),
                status_code=_as_optional_int(item.get("statusCode")),
                shopping_type="DELIVERY",
                transaction_completed=_as_optional_bool(item.get("transactionCompleted")),
                modifiable=_as_optional_bool(item.get("modifiable")),
                cancellable=_as_optional_bool(item.get("cancellable")),
                reopenable=_as_optional_bool(item.get("reopenable")),
                closing_date_time=_as_optional_str(item.get("closingDateTime")),
                slot_start=start,
                slot_end=end,
                slot_display=_as_optional_str(slot.get("timeDisplay")),
                delivery_date_display=_as_optional_str(slot.get("dateDisplay")),
                delivery_date_display_short=_as_optional_str(slot.get("dateDisplayShort")),
                delivery_day_display=_as_optional_str(slot.get("dayDisplay")),
                delivery_method=_as_optional_str(delivery.get("method")),
                delivery_message=_as_optional_str(delivery.get("deliveryMessage")),
                shift_code=_as_optional_str(delivery.get("shiftCode")),
                home_shop_center_id=_as_optional_int(delivery.get("homeShopCenterId")),
                ride_number=_as_optional_int(ride.get("number")),
                ride_sequence_number=_as_optional_int(ride.get("sequenceNumber")),
                ride_home_shop_center_id=_as_optional_int(ride.get("homeShopCenterId")),
                eta=eta,
                eta_lower=eta_lower,
                eta_upper=eta_upper,
                eta_status=eta_status,
                eta_observed_at=eta_observed,
            )
        )

    deliveries.sort(key=lambda d: d.slot_start)
    return tuple(deliveries)


def select_next_delivery(
    deliveries: tuple[Delivery, ...], now: datetime
) -> Delivery | None:
    """Select the next relevant delivery, retaining late active deliveries."""
    grace = timedelta(hours=2)
    for delivery in deliveries:
        relevant_until = delivery.slot_end + grace
        for candidate in (delivery.eta, delivery.eta_upper):
            if candidate is not None and candidate > relevant_until:
                relevant_until = candidate
        if relevant_until >= now:
            return delivery
    return None
