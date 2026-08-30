"""Albert Heijn Delivery integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AhApiClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    PLATFORMS,
)
from .coordinator import AhDeliveryCoordinator


@dataclass(slots=True)
class AhDeliveryRuntimeData:
    client: AhApiClient
    coordinator: AhDeliveryCoordinator


type AhDeliveryConfigEntry = ConfigEntry[AhDeliveryRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: AhDeliveryConfigEntry) -> bool:
    """Set up Albert Heijn Delivery from a config entry."""

    async def save_tokens(token_data: dict[str, Any]) -> None:
        new_data = {**entry.data, **token_data}
        hass.config_entries.async_update_entry(entry, data=new_data)

    client = AhApiClient(
        async_get_clientsession(hass),
        access_token=str(entry.data.get(CONF_ACCESS_TOKEN, "")),
        refresh_token=str(entry.data.get(CONF_REFRESH_TOKEN, "")),
        expires_at=float(entry.data.get(CONF_EXPIRES_AT, 0) or 0),
        member_id=str(entry.data.get(CONF_MEMBER_ID, "")),
        token_update_callback=save_tokens,
    )
    coordinator = AhDeliveryCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = AhDeliveryRuntimeData(client, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AhDeliveryConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
