"""Data update coordinator for Albert Heijn Delivery."""

from __future__ import annotations

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
    UPDATE_WITHIN_24H,
    UPDATE_WITHIN_3H,
)
from .exceptions import AhAuthError, AhRateLimitError, AhTransientError
from .models import DeliveryData, select_next_delivery

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
        _, source = delivery.best_time(now, int(ETA_MAX_AGE.total_seconds()))
        if source == "live_eta":
            return UPDATE_ACTIVE_ETA
        until_start = delivery.slot_start - now
        if until_start <= timedelta(hours=3):
            return UPDATE_WITHIN_3H
        if until_start <= timedelta(hours=24):
            return UPDATE_WITHIN_24H
        return DEFAULT_UPDATE_INTERVAL

    async def _async_update_data(self) -> DeliveryData:
        fetched_at = dt_util.now()
        try:
            deliveries = await self.client.async_get_open_deliveries(
                self.hass.config.time_zone, fetched_at
            )
        except AhAuthError as err:
            raise ConfigEntryAuthFailed("Albert Heijn authentication needs to be renewed") from err
        except AhRateLimitError as err:
            self._rate_limit_backoff = min(self._rate_limit_backoff + 1, 4)
            minutes = (10, 20, 40, 60)[self._rate_limit_backoff - 1]
            if err.retry_after:
                minutes = max(minutes, (err.retry_after + 59) // 60)
            self.update_interval = timedelta(minutes=minutes)
            raise UpdateFailed(f"Albert Heijn rate limited requests; backing off for {minutes} minutes") from err
        except AhTransientError as err:
            raise UpdateFailed(str(err)) from err

        self._rate_limit_backoff = 0
        next_delivery = select_next_delivery(deliveries, fetched_at)
        data = DeliveryData(
            deliveries=deliveries,
            next_delivery=next_delivery,
            fetched_at=fetched_at,
            rich_eta_supported=self.client.rich_query_supported,
        )
        self.update_interval = self._choose_interval(data)
        return data
