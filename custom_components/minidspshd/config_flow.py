"""Config flow for MiniDSP SHD integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.selector import EntitySelector
from pyvolumio import CannotConnectError, Volumio
import voluptuous as vol

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_ID, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DATA_POWER_CONSUMPTION, DATA_POWER_BUTTON, DATA_HAS_POWER_BUTTON
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str, vol.Required(CONF_PORT, default=3000): int,
        vol.Optional("power_consumption_entity"): EntitySelector(),
        vol.Optional("power_button"): EntitySelector()
    }
)


async def validate_input(hass: HomeAssistant, host: str, port: int) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    volumio = Volumio(host, port, async_get_clientsession(hass))
    try:
        return await volumio.get_system_info()
    except CannotConnectError as error:
        raise CannotConnect from error


class VolumioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Volumio."""

    VERSION = 1

    _host: str
    _port: int
    _name: str
    _uuid: str | None
    _power_consumption_entity: RegistryEntry | None
    _power_button: RegistryEntry | None
    _has_power_button: bool
    def __init__(self):
        self._has_power_button = self._power_consumption_entity is not None and self._power_button is not None

    @callback
    def _async_get_entry(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._name,
            data={
                CONF_NAME: self._name,
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_ID: self._uuid,
                DATA_POWER_CONSUMPTION: self._power_consumption_entity,
                DATA_POWER_BUTTON: self._power_button,
                DATA_HAS_POWER_BUTTON: self._has_power_button
            },
        )

    async def _set_uid_and_abort(self):
        await self.async_set_unique_id(self._uuid)
        self._abort_if_unique_id_configured(
            updates={
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_NAME: self._name,
            }
        )

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            info = None
            self._host = user_input[CONF_HOST]
            self._port = user_input[CONF_PORT]

            entity_registry = await self.hass.helpers.entity_registry.async_get_registry()
            power_consumption_entity = await entity_registry.async_get(user_input["power_consumption_entity"])
            if power_consumption_entity is None:
                errors["power_consumption_entity"] = "entity_not_found"
            elif power_consumption_entity.capabilities.get("device_class") != "energy":
                errors["power_consumption_entity"] = "not_an_energy_sensor"
            else:
                self._power_consumption_entity = power_consumption_entity

            power_button = await entity_registry.async_get(user_input["power_button"])
            if power_button is None:
                errors["power_button"] = "entity_not_found"
            elif power_button.domain != "button":
                errors["power_button"] = "not_a_button"
            else:
                self._power_button = power_button

            try:
                info = await validate_input(self.hass, self._host, self._port)

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            if info is not None:
                self._name = info.get("name", self._host)
                self._uuid = info.get("id")
                if self._uuid is not None:
                    await self._set_uid_and_abort()

                return self._async_get_entry()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(
            self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        self._host = discovery_info.host
        self._port = discovery_info.port or 3000
        self._name = discovery_info.properties["volumioName"]
        self._uuid = discovery_info.properties["UUID"]

        await self._set_uid_and_abort()

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-confirmation of discovered node."""
        if user_input is not None:
            try:
                await validate_input(self.hass, self._host, self._port)
                return self._async_get_entry()
            except CannotConnect:
                return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="discovery_confirm", description_placeholders={"name": self._name}
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
