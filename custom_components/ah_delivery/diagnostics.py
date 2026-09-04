"""Diagnostics for Albert Heijn Delivery."""

from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.core import HomeAssistant

from . import AhDeliveryConfigEntry, AhDeliveryRuntimeData


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AhDeliveryConfigEntry
) -> dict[str, Any]:
    """Return extensive privacy-safe diagnostics; never include account secrets."""
    runtime: AhDeliveryRuntimeData = entry.runtime_data
    data = runtime.coordinator.data
    delivery = data.next_delivery if data else None
    order_hash = (
        hashlib.sha256(str(delivery.order_id).encode()).hexdigest()[:12]
        if delivery and delivery.order_id is not None
        else None
    )
    return {
        "integration": "ah_delivery",
        "timezone": hass.config.time_zone,
        "rich_eta_supported": data.rich_eta_supported if data else None,
        "open_delivery_count": len(data.deliveries) if data else 0,
        "last_successful_update": data.fetched_at.isoformat() if data else None,
        "update_interval_seconds": (
            int(runtime.coordinator.update_interval.total_seconds())
            if runtime.coordinator.update_interval
            else None
        ),
        "next_delivery": (
            {
                "order_id_hash": order_hash,
                "status": delivery.status,
                "status_description": delivery.status_description,
                "status_code": delivery.status_code,
                "delivery_method": delivery.delivery_method,
                "delivery_message": delivery.delivery_message,
                "slot_start": delivery.slot_start.isoformat(),
                "slot_end": delivery.slot_end.isoformat(),
                "slot_display": delivery.slot_display,
                "eta": delivery.eta.isoformat() if delivery.eta else None,
                "eta_lower": delivery.eta_lower.isoformat() if delivery.eta_lower else None,
                "eta_upper": delivery.eta_upper.isoformat() if delivery.eta_upper else None,
                "eta_status": delivery.eta_status,
                "eta_observed_at": (
                    delivery.eta_observed_at.isoformat()
                    if delivery.eta_observed_at
                    else None
                ),
                "ride_number": delivery.ride_number,
                "ride_sequence_number": delivery.ride_sequence_number,
                "shift_code": delivery.shift_code,
                "home_shop_center_id": delivery.home_shop_center_id,
            }
            if delivery
            else None
        ),
        # This snapshot is sanitized before it reaches the coordinator: tokens,
        # account identifiers, addresses and plain order IDs are removed.
        "api_diagnostics": data.diagnostics if data else {},
    }
