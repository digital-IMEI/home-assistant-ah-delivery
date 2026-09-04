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


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:255]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhDeliveryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AH Delivery sensor entities."""
    runtime: AhDeliveryRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    async_add_entities(
        [
            AhNextDeliverySensor(coordinator, entry),
            AhSlotStartSensor(coordinator, entry),
            AhSlotEndSensor(coordinator, entry),
            AhLiveEtaSensor(coordinator, entry),
            AhEtaLowerSensor(coordinator, entry),
            AhEtaUpperSensor(coordinator, entry),
            AhEtaWindowSensor(coordinator, entry),
            AhEtaStatusSensor(coordinator, entry),
            AhDeliveryStatusSensor(coordinator, entry),
            AhDeliveryMessageSensor(coordinator, entry),
            AhDeliveryMethodSensor(coordinator, entry),
            AhRideNumberSensor(coordinator, entry),
            AhRideSequenceSensor(coordinator, entry),
            AhShiftCodeSensor(coordinator, entry),
            AhHomeShopCenterSensor(coordinator, entry),
            AhSlotDisplaySensor(coordinator, entry),
            AhDateDisplaySensor(coordinator, entry),
            AhStatusCodeSensor(coordinator, entry),
            AhApiDiagnosticsSensor(coordinator, entry),
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
        _, source = delivery.best_time(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        )
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
                "eta_observed_at": (
                    delivery.eta_observed_at.isoformat()
                    if delivery.eta_observed_at
                    else None
                ),
                "delivery_status": delivery.status,
                "status_description": delivery.status_description,
                "delivery_message": delivery.delivery_message,
                "ride_number": delivery.ride_number,
                "ride_sequence_number": delivery.ride_sequence_number,
            }
        )
        return attrs


class _DiagnosticSensor(AhDeliveryBaseEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # This release is deliberately diagnostic-heavy. New diagnostic entities are
    # enabled so tonight's one-off delivery cannot pass without being captured.
    _attr_entity_registry_enabled_default = True


class _TimestampDiagnostic(_DiagnosticSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP


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
        if not self.delivery.eta_is_fresh(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        ):
            return None
        return self.delivery.eta


class AhEtaLowerSensor(_TimestampDiagnostic):
    _attr_translation_key = "eta_lower"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_eta_lower"

    @property
    def native_value(self) -> datetime | None:
        if not self.delivery or not self.delivery.eta_is_fresh(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        ):
            return None
        return self.delivery.eta_lower


class AhEtaUpperSensor(_TimestampDiagnostic):
    _attr_translation_key = "eta_upper"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_eta_upper"

    @property
    def native_value(self) -> datetime | None:
        if not self.delivery or not self.delivery.eta_is_fresh(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        ):
            return None
        return self.delivery.eta_upper


class AhEtaWindowSensor(_DiagnosticSensor):
    _attr_translation_key = "eta_window"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_eta_window"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        window = self.delivery.eta_window(
            dt_util.now(), int(ETA_MAX_AGE.total_seconds())
        )
        if window is None:
            return None
        lower, upper = window
        if lower and upper:
            return f"{lower:%H:%M}–{upper:%H:%M}"
        if lower:
            return f"vanaf {lower:%H:%M}"
        if upper:
            return f"voor {upper:%H:%M}"
        return None


class AhEtaStatusSensor(_DiagnosticSensor):
    _attr_translation_key = "eta_status"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_eta_status"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.eta_status) if self.delivery else None


class AhDeliveryStatusSensor(_DiagnosticSensor):
    _attr_translation_key = "delivery_status"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_delivery_status"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.status) if self.delivery else None


class AhDeliveryMessageSensor(_DiagnosticSensor):
    _attr_translation_key = "delivery_message"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_delivery_message"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.delivery_message) if self.delivery else None


class AhDeliveryMethodSensor(_DiagnosticSensor):
    _attr_translation_key = "delivery_method"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_delivery_method"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.delivery_method) if self.delivery else None


class AhRideNumberSensor(_DiagnosticSensor):
    _attr_translation_key = "ride_number"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_ride_number"

    @property
    def native_value(self) -> int | None:
        return self.delivery.ride_number if self.delivery else None


class AhRideSequenceSensor(_DiagnosticSensor):
    _attr_translation_key = "ride_sequence"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_ride_sequence"

    @property
    def native_value(self) -> int | None:
        return self.delivery.ride_sequence_number if self.delivery else None


class AhShiftCodeSensor(_DiagnosticSensor):
    _attr_translation_key = "shift_code"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_shift_code"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.shift_code) if self.delivery else None


class AhHomeShopCenterSensor(_DiagnosticSensor):
    _attr_translation_key = "home_shop_center"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_home_shop_center"

    @property
    def native_value(self) -> int | None:
        return self.delivery.home_shop_center_id if self.delivery else None


class AhSlotDisplaySensor(_DiagnosticSensor):
    _attr_translation_key = "slot_display"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_slot_display"

    @property
    def native_value(self) -> str | None:
        return _safe_text(self.delivery.slot_display) if self.delivery else None


class AhDateDisplaySensor(_DiagnosticSensor):
    _attr_translation_key = "date_display"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_date_display"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        return _safe_text(
            self.delivery.delivery_date_display_short
            or self.delivery.delivery_date_display
            or self.delivery.delivery_day_display
        )


class AhStatusCodeSensor(_DiagnosticSensor):
    _attr_translation_key = "status_code"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_status_code"

    @property
    def native_value(self) -> int | None:
        return self.delivery.status_code if self.delivery else None


class AhApiDiagnosticsSensor(_DiagnosticSensor):
    """One capture entity containing all privacy-safe probe results."""

    _attr_translation_key = "api_diagnostics"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_api_diagnostics"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if not data:
            return "no_data"
        probes = data.diagnostics.get("probes", {})
        rich = probes.get("rich_fulfillments", {}) if isinstance(probes, dict) else {}
        if isinstance(rich, dict) and rich.get("ok") is True:
            return "rich"
        return "fallback"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        delivery = self.delivery
        parsed: dict[str, Any] | None = None
        if delivery:
            order_hash = (
                hashlib.sha256(str(delivery.order_id).encode()).hexdigest()[:12]
                if delivery.order_id is not None
                else None
            )
            parsed = {
                "order_id_hash": order_hash,
                "status": delivery.status,
                "status_description": delivery.status_description,
                "status_code": delivery.status_code,
                "transaction_completed": delivery.transaction_completed,
                "modifiable": delivery.modifiable,
                "cancellable": delivery.cancellable,
                "reopenable": delivery.reopenable,
                "closing_date_time": delivery.closing_date_time,
                "delivery_method": delivery.delivery_method,
                "delivery_message": delivery.delivery_message,
                "shift_code": delivery.shift_code,
                "home_shop_center_id": delivery.home_shop_center_id,
                "ride_number": delivery.ride_number,
                "ride_sequence_number": delivery.ride_sequence_number,
                "ride_home_shop_center_id": delivery.ride_home_shop_center_id,
                "slot_start": delivery.slot_start.isoformat(),
                "slot_end": delivery.slot_end.isoformat(),
                "slot_display": delivery.slot_display,
                "delivery_date_display": delivery.delivery_date_display,
                "delivery_date_display_short": delivery.delivery_date_display_short,
                "delivery_day_display": delivery.delivery_day_display,
                "eta": delivery.eta.isoformat() if delivery.eta else None,
                "eta_lower": delivery.eta_lower.isoformat() if delivery.eta_lower else None,
                "eta_upper": delivery.eta_upper.isoformat() if delivery.eta_upper else None,
                "eta_status": delivery.eta_status,
                "eta_observed_at": (
                    delivery.eta_observed_at.isoformat()
                    if delivery.eta_observed_at
                    else None
                ),
            }
        return {
            "captured_at": data.fetched_at.isoformat(),
            "open_deliveries": len(data.deliveries),
            "update_interval_seconds": (
                int(self.coordinator.update_interval.total_seconds())
                if self.coordinator.update_interval
                else None
            ),
            "parsed_delivery": parsed,
            "api": data.diagnostics,
        }
