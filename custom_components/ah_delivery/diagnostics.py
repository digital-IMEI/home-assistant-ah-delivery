"""Diagnostics for Albert Heijn Delivery."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import AhDeliveryConfigEntry, AhDeliveryRuntimeData


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AhDeliveryConfigEntry
) -> dict[str, Any]:
    """Return privacy-safe diagnostics; never include tokens, address, or order IDs."""
    runtime: AhDeliveryRuntimeData = entry.runtime_data
    data = runtime.coordinator.data
    return {
        "integration": "ah_delivery",
        "timezone": hass.config.time_zone,
        "rich_eta_supported": data.rich_eta_supported if data else None,
        "open_delivery_count": len(data.deliveries) if data else 0,
        "last_successful_update": data.fetched_at.isoformat() if data else None,
        "next_delivery": (
            {
                "status": data.next_delivery.status,
                "slot_start": data.next_delivery.slot_start.isoformat(),
                "slot_end": data.next_delivery.slot_end.isoformat(),
                "has_eta": data.next_delivery.eta is not None,
            }
            if data and data.next_delivery
            else None
        ),
    }
