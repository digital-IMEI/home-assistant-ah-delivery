"""Binary sensors for Albert Heijn Delivery."""

from __future__ import annotations

import hashlib

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import AhDeliveryConfigEntry
from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhDeliveryCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhDeliveryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AH Delivery binary sensors."""
    coordinator: AhDeliveryCoordinator = entry.runtime_data.coordinator
    async_add_entities([AhDeliveryTodayBinarySensor(coordinator, entry)])


class AhDeliveryTodayBinarySensor(
    CoordinatorEntity[AhDeliveryCoordinator], BinarySensorEntity
):
    """Whether the currently selected next AH delivery is today."""

    _attr_has_entity_name = True
    _attr_translation_key = "delivery_today"
    _attr_icon = "mdi:truck-delivery"
    _attr_entity_registry_enabled_default = True
    _attr_suggested_object_id = "ah_bezorging_vandaag"

    def __init__(
        self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry
    ) -> None:
        super().__init__(coordinator)
        member = str(entry.data.get(CONF_MEMBER_ID, ""))
        source = member or entry.entry_id
        account_key = hashlib.sha256(source.encode()).hexdigest()[:16]
        self._attr_unique_id = f"{account_key}_delivery_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_key)},
            manufacturer="Albert Heijn",
            model="Delivery",
            name="AH",
        )

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        delivery = data.next_delivery if data else None
        if delivery is None:
            return False
        return (
            dt_util.as_local(delivery.slot_start).date()
            == dt_util.now().date()
        )
