"""Config flow for MiniDSP SHD integration."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

import voluptuous as vol
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_ID, CONF_NAME, CONF_PORT, CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from pyvolumio import CannotConnectError, Volumio

from .const import DOMAIN, CONF_MINIDSP_API, CONF_MINIDSP_API_DEVICE_ID
from .minidsp_api import MiniDSPApi

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=3000): int,
        vol.Optional(CONF_MINIDSP_API): section(vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=5380): int,
            vol.Required(CONF_MINIDSP_API_DEVICE_ID, default=0): int,
        })),
        vol.Optional(CONF_ENTITY_ID): EntitySelector(EntitySelectorConfig(domain="switch"))
    }
)


async def validate_volumio_input(hass: HomeAssistant, host: str, port: int) -> dict[str, Any]:
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
    _power: str | None
    _api: MiniDSPApi | None

    @callback
    def _async_get_entry(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._name,
            data={
                CONF_NAME: self._name,
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_ID: self._uuid,
                CONF_ENTITY_ID: self._power,
                CONF_MINIDSP_API: asdict(self._api)
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

            entity_registry = async_get(self.hass)

            if user_input.get(CONF_ENTITY_ID, None) is not None:
                sw = entity_registry.async_get(user_input[CONF_ENTITY_ID])
                if sw.domain != "switch":
                    errors[CONF_ENTITY_ID] = "not_a_switch"
                else:
                    self._power = user_input[CONF_ENTITY_ID]

            api = user_input.get(CONF_MINIDSP_API, None)
            if api is not None:
                api_host = api.get(CONF_HOST, None)
                if api_host is None:
                    errors[CONF_MINIDSP_API] = "not_filled_in"

                api_port = int(api[CONF_PORT])
                device_id = int(api[CONF_MINIDSP_API_DEVICE_ID])
                api_instance = MiniDSPApi(api_host, api_port, device_id)
                self._api = api_instance
                try:
                    await self.hass.async_add_executor_job(self._api.verify_ws_connection)
                except Exception as error:
                    errors[CONF_MINIDSP_API] = "cannot_connect"
                    raise CannotConnect from error

            try:
                info = await validate_volumio_input(self.hass, self._host, self._port)

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
        self._power = None
        self._api = None

        await self._set_uid_and_abort()

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-confirmation of discovered node."""
        if user_input is not None:
            try:
                await validate_volumio_input(self.hass, self._host, self._port)
                return self._async_get_entry()
            except CannotConnect:
                return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="discovery_confirm", description_placeholders={"name": self._name}
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
