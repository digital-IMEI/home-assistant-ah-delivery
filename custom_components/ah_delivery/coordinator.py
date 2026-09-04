"""Data update coordinator for Albert Heijn Delivery."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AhApiClient
from .const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ETA_MAX_AGE,
    UPDATE_ACTIVE_ETA,
    UPDATE_MORE_THAN_7D,
    UPDATE_WITHIN_24H,
    UPDATE_WITHIN_3H,
    UPDATE_WITHIN_48H,
    UPDATE_WITHIN_7D,
)
from .exceptions import AhAuthError, AhRateLimitError, AhTransientError
from .models import DeliveryData, apply_track_trace, select_next_delivery
from .track_trace import async_fetch_track_trace

_LOGGER = logging.getLogger(__name__)


class AhDeliveryCoordinator(DataUpdateCoordinator[DeliveryData]):
    """Coordinate AH delivery updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AhApiClient) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            always_update=False,
            config_entry=entry,
        )
        self.client = client
        self._rate_limit_backoff = 0

    def _choose_interval(self, data: DeliveryData) -> timedelta:
        delivery = data.next_delivery
        if delivery is None:
            return DEFAULT_UPDATE_INTERVAL

        now = dt_util.now()
        max_age = int(ETA_MAX_AGE.total_seconds())
        track_type = str(delivery.track_type or "").upper()
        track_live = delivery.track_is_fresh(now, max_age) and (
            delivery.track_eta_start is not None
            or delivery.track_eta_end is not None
            or track_type.startswith("UNDERWAY")
            or track_type in {"IN_TRANSIT", "PREPARING"}
        )
        if delivery.eta_is_fresh(now, max_age) or track_live:
            return UPDATE_ACTIVE_ETA

        until_start = delivery.slot_start - now
        if until_start <= timedelta(hours=3):
            return UPDATE_WITHIN_3H
        if until_start <= timedelta(hours=24):
            return UPDATE_WITHIN_24H
        if until_start <= timedelta(hours=48):
            return UPDATE_WITHIN_48H
        if until_start <= timedelta(days=7):
            return UPDATE_WITHIN_7D
        return UPDATE_MORE_THAN_7D

    async def _async_update_data(self) -> DeliveryData:
        fetched_at = dt_util.now()
        try:
            deliveries = await self.client.async_get_open_deliveries(
                self.hass.config.time_zone, fetched_at
            )
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(
                "Albert Heijn authentication needs to be renewed"
            ) from err
        except AhRateLimitError as err:
            self._rate_limit_backoff = min(self._rate_limit_backoff + 1, 4)
            minutes = (10, 20, 40, 60)[self._rate_limit_backoff - 1]
            if err.retry_after:
                minutes = max(minutes, (err.retry_after + 59) // 60)
            self.update_interval = timedelta(minutes=minutes)
            raise UpdateFailed(
                f"Albert Heijn rate limited requests; backing off for {minutes} minutes"
            ) from err
        except AhTransientError as err:
            raise UpdateFailed(str(err)) from err

        self._rate_limit_backoff = 0
        diagnostics = deepcopy(self.client.diagnostic_snapshot)
        diagnostics.setdefault("probes", {})

        next_before_track = select_next_delivery(deliveries, fetched_at)
        delivery_is_today = bool(
            next_before_track
            and dt_util.as_local(next_before_track.slot_start).date()
            == dt_util.as_local(fetched_at).date()
        )

        # Track & Trace is useful on the actual delivery day. Avoid the extra
        # GraphQL call for orders that are still days away.
        if (
            next_before_track
            and next_before_track.order_id is not None
            and delivery_is_today
        ):
            track, track_diagnostics = await async_fetch_track_trace(
                self.client,
                next_before_track.order_id,
                self.hass.config.time_zone,
                fetched_at,
                next_before_track.slot_start.date().isoformat(),
            )
            diagnostics["probes"]["track_and_trace_v2"] = track_diagnostics
            deliveries = apply_track_trace(deliveries, track)
        elif next_before_track and not delivery_is_today:
            diagnostics["probes"]["track_and_trace_v2"] = {
                "ok": False,
                "skipped": True,
                "error": "delivery is not today; skipped for efficiency",
            }
        else:
            diagnostics["probes"]["track_and_trace_v2"] = {
                "ok": False,
                "skipped": True,
                "error": "no relevant open DELIVERY order",
            }

        next_delivery = select_next_delivery(deliveries, fetched_at)
        data = DeliveryData(
            deliveries=deliveries,
            next_delivery=next_delivery,
            fetched_at=fetched_at,
            rich_eta_supported=self.client.rich_query_supported,
            diagnostics=diagnostics,
        )
        self.update_interval = self._choose_interval(data)
        return data
