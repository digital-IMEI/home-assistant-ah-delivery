"""Sensors for Albert Heijn Delivery."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
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
    return value[:255] if value is not None else None


def _window_text(start: datetime | None, end: datetime | None) -> str | None:
    if start and end:
        if start == end:
            return f"{start:%H:%M}"
        return f"{start:%H:%M}–{end:%H:%M}"
    if start:
        return f"vanaf {start:%H:%M}"
    if end:
        return f"voor {end:%H:%M}"
    return None


def _max_age() -> int:
    return int(ETA_MAX_AGE.total_seconds())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhDeliveryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AH Delivery sensor entities."""
    coordinator: AhDeliveryCoordinator = entry.runtime_data.coordinator

    entities: list[SensorEntity] = [
        AhNextDeliverySensor(coordinator, entry),
        AhEtaWindowSensor(coordinator, entry),
        AhTrackEtaWindowSensor(coordinator, entry),
        AhExpectedArrivalWindowSensor(coordinator, entry),
        AhExpectedSourceSensor(coordinator, entry),
        AhLastUpdateSensor(coordinator, entry),
        AhUpdateIntervalSensor(coordinator, entry),
        AhApiDiagnosticsSensor(coordinator, entry),
    ]

    field_specs: list[tuple[str, str, Callable[[Delivery], Any], SensorDeviceClass | None]] = [
        ("slot_start", "slot_start", lambda d: d.slot_start, SensorDeviceClass.TIMESTAMP),
        ("slot_end", "slot_end", lambda d: d.slot_end, SensorDeviceClass.TIMESTAMP),
        (
            "live_eta",
            "live_eta",
            lambda d: d.eta if d.eta_is_fresh(dt_util.now(), _max_age()) else None,
            SensorDeviceClass.TIMESTAMP,
        ),
        (
            "eta_lower",
            "eta_lower",
            lambda d: d.eta_lower if d.eta_is_fresh(dt_util.now(), _max_age()) else None,
            SensorDeviceClass.TIMESTAMP,
        ),
        (
            "eta_upper",
            "eta_upper",
            lambda d: d.eta_upper if d.eta_is_fresh(dt_util.now(), _max_age()) else None,
            SensorDeviceClass.TIMESTAMP,
        ),
        ("eta_status", "eta_status", lambda d: _safe_text(d.eta_status), None),
        ("delivery_status", "delivery_status", lambda d: _safe_text(d.status), None),
        ("delivery_message", "delivery_message", lambda d: _safe_text(d.delivery_message), None),
        ("delivery_method", "delivery_method", lambda d: _safe_text(d.delivery_method), None),
        ("ride_number", "ride_number", lambda d: d.ride_number, None),
        ("ride_sequence", "ride_sequence", lambda d: d.ride_sequence_number, None),
        ("shift_code", "shift_code", lambda d: _safe_text(d.shift_code), None),
        ("home_shop_center", "home_shop_center", lambda d: d.home_shop_center_id, None),
        ("slot_display", "slot_display", lambda d: _safe_text(d.slot_display), None),
        (
            "date_display",
            "date_display",
            lambda d: _safe_text(
                d.delivery_date_display_short
                or d.delivery_date_display
                or d.delivery_day_display
            ),
            None,
        ),
        ("status_code", "status_code", lambda d: d.status_code, None),
        ("track_trace_type", "track_trace_type", lambda d: _safe_text(d.track_type), None),
        ("track_order_type", "track_order_type", lambda d: _safe_text(d.track_order_type), None),
        ("track_message", "track_message", lambda d: _safe_text(d.track_message), None),
        (
            "track_eta_start",
            "track_eta_start",
            lambda d: d.track_eta_start if d.track_is_fresh(dt_util.now(), _max_age()) else None,
            SensorDeviceClass.TIMESTAMP,
        ),
        (
            "track_eta_end",
            "track_eta_end",
            lambda d: d.track_eta_end if d.track_is_fresh(dt_util.now(), _max_age()) else None,
            SensorDeviceClass.TIMESTAMP,
        ),
        (
            "realised_delivery_time",
            "realised_delivery_time",
            lambda d: d.track_realised_delivery_time,
            SensorDeviceClass.TIMESTAMP,
        ),
        (
            "track_observed_at",
            "track_observed_at",
            lambda d: d.track_observed_at,
            SensorDeviceClass.TIMESTAMP,
        ),
    ]
    entities.extend(
        AhDiagnosticFieldSensor(
            coordinator,
            entry,
            unique_key=unique_key,
            translation_key=translation_key,
            value_getter=value_getter,
            device_class=device_class,
        )
        for unique_key, translation_key, value_getter, device_class in field_specs
    )
    async_add_entities(entities)


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


class _DiagnosticSensor(AhDeliveryBaseEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True


class AhDiagnosticFieldSensor(_DiagnosticSensor):
    """Small generic diagnostic field entity while capture is intentionally broad."""

    def __init__(
        self,
        coordinator: AhDeliveryCoordinator,
        entry: AhDeliveryConfigEntry,
        *,
        unique_key: str,
        translation_key: str,
        value_getter: Callable[[Delivery], Any],
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_{unique_key}"
        self._attr_translation_key = translation_key
        self._value_getter = value_getter
        if device_class is not None:
            self._attr_device_class = device_class

    @property
    def native_value(self) -> Any:
        if self.delivery is None:
            return None
        return self._value_getter(self.delivery)


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
        return self.delivery.best_time(dt_util.now(), _max_age())[0]

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
        _, source = delivery.best_time(dt_util.now(), _max_age())
        window_start, window_end, window_source = delivery.expected_window(
            dt_util.now(), _max_age()
        )
        attrs.update(
            {
                "source": source,
                "expected_window_source": window_source,
                "expected_window_start": window_start.isoformat() if window_start else None,
                "expected_window_end": window_end.isoformat() if window_end else None,
                "delivery_date": delivery.slot_start.date().isoformat(),
                "slot_start": delivery.slot_start.isoformat(),
                "slot_end": delivery.slot_end.isoformat(),
                "slot": delivery.slot_display,
                "eta": delivery.eta.isoformat() if delivery.eta else None,
                "eta_lower": delivery.eta_lower.isoformat() if delivery.eta_lower else None,
                "eta_upper": delivery.eta_upper.isoformat() if delivery.eta_upper else None,
                "eta_status": delivery.eta_status,
                "eta_observed_at": delivery.eta_observed_at.isoformat() if delivery.eta_observed_at else None,
                "track_type": delivery.track_type,
                "track_order_type": delivery.track_order_type,
                "track_message": delivery.track_message,
                "track_eta_start": delivery.track_eta_start.isoformat() if delivery.track_eta_start else None,
                "track_eta_end": delivery.track_eta_end.isoformat() if delivery.track_eta_end else None,
                "track_realised_delivery_time": (
                    delivery.track_realised_delivery_time.isoformat()
                    if delivery.track_realised_delivery_time
                    else None
                ),
                "track_observed_at": delivery.track_observed_at.isoformat() if delivery.track_observed_at else None,
                "delivery_status": delivery.status,
                "status_description": delivery.status_description,
                "delivery_message": delivery.delivery_message,
                "ride_number": delivery.ride_number,
                "ride_sequence_number": delivery.ride_sequence_number,
            }
        )
        return attrs


class AhEtaWindowSensor(_DiagnosticSensor):
    _attr_translation_key = "eta_window"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_eta_window"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        window = self.delivery.eta_window(dt_util.now(), _max_age())
        return _window_text(*window) if window is not None else None


class AhTrackEtaWindowSensor(_DiagnosticSensor):
    _attr_translation_key = "track_eta_window"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_track_eta_window"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        window = self.delivery.track_window(dt_util.now(), _max_age())
        return _window_text(*window) if window is not None else None


class AhExpectedArrivalWindowSensor(_DiagnosticSensor):
    _attr_translation_key = "expected_arrival_window"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_expected_arrival_window"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        start, end, _ = self.delivery.expected_window(dt_util.now(), _max_age())
        return _window_text(start, end)


class AhExpectedSourceSensor(_DiagnosticSensor):
    _attr_translation_key = "expected_source"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_expected_source"

    @property
    def native_value(self) -> str | None:
        if not self.delivery:
            return None
        return self.delivery.expected_window(dt_util.now(), _max_age())[2]


class AhLastUpdateSensor(_DiagnosticSensor):
    _attr_translation_key = "last_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_last_update"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.fetched_at if self.coordinator.data else None


class AhUpdateIntervalSensor(_DiagnosticSensor):
    _attr_translation_key = "update_interval"

    def __init__(self, coordinator: AhDeliveryCoordinator, entry: AhDeliveryConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._account_key}_update_interval"

    @property
    def native_value(self) -> int | None:
        return (
            int(self.coordinator.update_interval.total_seconds())
            if self.coordinator.update_interval
            else None
        )


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
        if isinstance(probes, dict):
            track = probes.get("track_and_trace_v2", {})
            if isinstance(track, dict) and track.get("ok") is True and track.get("available") is True:
                return "track_and_trace"
            rich = probes.get("rich_fulfillments", {})
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
                "eta_observed_at": delivery.eta_observed_at.isoformat() if delivery.eta_observed_at else None,
                "track_type": delivery.track_type,
                "track_order_type": delivery.track_order_type,
                "track_message": delivery.track_message,
                "track_eta_start": delivery.track_eta_start.isoformat() if delivery.track_eta_start else None,
                "track_eta_end": delivery.track_eta_end.isoformat() if delivery.track_eta_end else None,
                "track_realised_delivery_time": (
                    delivery.track_realised_delivery_time.isoformat()
                    if delivery.track_realised_delivery_time
                    else None
                ),
                "track_observed_at": delivery.track_observed_at.isoformat() if delivery.track_observed_at else None,
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
