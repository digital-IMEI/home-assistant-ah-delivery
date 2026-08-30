"""Sensors for Albert Heijn Delivery."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import AhDeliveryConfigEntry, AhDeliveryRuntimeData
from .const import CONF_MEMBER_ID, DOMAIN, ETA_MAX_AGE
from .coordinator import AhDeliveryCoordinator
from .models import Delivery


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhDeliveryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AH Delivery sensor entities."""
    runtime: AhDeliveryRuntimeData = entry.runtime_data
    async_add_entities(
        [
            AhNextDeliverySensor(runtime.coordinator, entry),
            AhSlotStartSensor(runtime.coordinator, entry),
            AhSlotEndSensor(runtime.coordinator, entry),
            AhLiveEtaSensor(runtime.coordinator, entry),
            AhDeliveryStatusSensor(runtime.coordinator, entry),
        ]
    )


class AhDeliveryBaseEntity(CoordinatorEntity[AhDeliveryCoordinator]):
    """Base coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        member = str(entry.data.get(CONF_MEMBER_ID, ""))
        source = member or entry.entry_id
        self._account_key = hashlib.sha256(source.encode()).hexdigest()[:16]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_key)},
            manufacturer="Albert Heijn",
            model="Delivery",
            name="AH",
        )

    @property
    def delivery(self) -> Delivery | None:
        return self.coordinator.data.next_delivery if self.coordinator.data else None


class AhNextDeliverySensor(AhDeliveryBaseEntity, SensorEntity):
    """Best available timestamp for the next delivery."""

    _attr_translation_key = "next_delivery"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_next_delivery"

    @property
    def native_value(self) -> datetime | None:
        if not self.delivery:
            return None
        return self.delivery.best_time(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        )[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        delivery = self.delivery
        attrs: dict[str, Any] = {
            "open_deliveries": len(data.deliveries) if data else 0,
            "last_successful_update": data.fetched_at.isoformat() if data else None,
            "eta_api_supported": data.rich_eta_supported if data else None,
        }
        if delivery is None:
            return attrs
        _, source = delivery.best_time(dt_util.now(), int(ETA_MAX_AGE.total_seconds()))
        attrs.update(
            {
                "source": source,
                "delivery_date": delivery.slot_start.date().isoformat(),
                "slot_start": delivery.slot_start.isoformat(),
                "slot_end": delivery.slot_end.isoformat(),
                "slot": delivery.slot_display,
                "eta": delivery.eta.isoformat() if delivery.eta else None,
                "eta_lower": delivery.eta_lower.isoformat() if delivery.eta_lower else None,
                "eta_upper": delivery.eta_upper.isoformat() if delivery.eta_upper else None,
                "eta_status": delivery.eta_status,
                "delivery_status": delivery.status,
                "status_description": delivery.status_description,
            }
        )
        return attrs


class _TimestampDiagnostic(AhDeliveryBaseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class AhSlotStartSensor(_TimestampDiagnostic):
    _attr_translation_key = "slot_start"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_slot_start"

    @property
    def native_value(self) -> datetime | None:
        return self.delivery.slot_start if self.delivery else None


class AhSlotEndSensor(_TimestampDiagnostic):
    _attr_translation_key = "slot_end"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_slot_end"

    @property
    def native_value(self) -> datetime | None:
        return self.delivery.slot_end if self.delivery else None


class AhLiveEtaSensor(_TimestampDiagnostic):
    _attr_translation_key = "live_eta"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_live_eta"

    @property
    def native_value(self) -> datetime | None:
        if not self.delivery:
            return None
        _, source = self.delivery.best_time(dt_util.now(), int(ETA_MAX_AGE.total_seconds()))
        return self.delivery.eta if source == "live_eta" else None


class AhDeliveryStatusSensor(AhDeliveryBaseEntity, SensorEntity):
    _attr_translation_key = "delivery_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_delivery_status"

    @property
    def native_value(self) -> str | None:
        return self.delivery.status if self.delivery else None
