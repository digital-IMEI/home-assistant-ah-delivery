"""Config flow for Albert Heijn Delivery."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AhApiClient
from .const import (
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    NAME,
)
from .exceptions import AhAuthError, AhDeliveryError, AhTransientError

CONF_AUTHORIZATION_CODE = "authorization_code"


def _schema() -> vol.Schema:
    return vol.Schema({vol.Required(CONF_AUTHORIZATION_CODE): str})


def _entry_data(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_ACCESS_TOKEN: tokens.get(CONF_ACCESS_TOKEN, ""),
        CONF_REFRESH_TOKEN: tokens.get(CONF_REFRESH_TOKEN, ""),
        CONF_EXPIRES_AT: tokens.get(CONF_EXPIRES_AT, 0),
        CONF_MEMBER_ID: tokens.get(CONF_MEMBER_ID, ""),
        "client_id": CLIENT_ID,
    }


class AhDeliveryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Albert Heijn Delivery config flow."""

    VERSION = 1

    async def _exchange(self, value: str) -> dict[str, Any]:
        """Exchange the code and verify the authenticated GraphQL connection."""
        client = AhApiClient(async_get_clientsession(self.hass))
        tokens = await client.exchange_authorization_code(value)
        # This succeeds even when the account has no open orders and ensures the
        # private API is actually usable before a config entry is created.
        from homeassistant.util import dt as dt_util

        await client.async_get_open_deliveries(self.hass.config.time_zone, dt_util.now())
        return tokens

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                tokens = await self._exchange(user_input[CONF_AUTHORIZATION_CODE])
            except AhAuthError:
                errors["base"] = "invalid_auth"
            except (AhTransientError, AhDeliveryError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_auth"
            else:
                refresh = str(tokens.get(CONF_REFRESH_TOKEN, ""))
                member = str(tokens.get(CONF_MEMBER_ID, ""))
                unique_source = member or refresh
                unique = hashlib.sha256(unique_source.encode()).hexdigest()[:24]
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data=_entry_data(tokens))

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(),
            errors=errors,
            description_placeholders={"login_url": AhApiClient.login_url()},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                tokens = await self._exchange(user_input[CONF_AUTHORIZATION_CODE])
            except AhAuthError:
                errors["base"] = "invalid_auth"
            except (AhTransientError, AhDeliveryError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_auth"
            else:
                entry = self._get_reauth_entry()
                member = str(tokens.get(CONF_MEMBER_ID, ""))
                if member and entry.unique_id:
                    new_unique = hashlib.sha256(member.encode()).hexdigest()[:24]
                    if new_unique != entry.unique_id:
                        errors["base"] = "wrong_account"
                    else:
                        return self.async_update_reload_and_abort(
                            entry, data_updates=_entry_data(tokens)
                        )
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates=_entry_data(tokens)
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(),
            errors=errors,
            description_placeholders={"login_url": AhApiClient.login_url()},
        )
