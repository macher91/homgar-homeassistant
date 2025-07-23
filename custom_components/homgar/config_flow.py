"""Config flow for HomGar integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api import HomgarApi, HomgarApiException
from .const import CONF_AREA_CODE, CONF_EMAIL, CONF_PASSWORD, DEFAULT_AREA_CODE, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_AREA_CODE, default=DEFAULT_AREA_CODE): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = HomgarApi()
    
    try:
        await hass.async_add_executor_job(
            api.login, data[CONF_EMAIL], data[CONF_PASSWORD], data[CONF_AREA_CODE]
        )
    except HomgarApiException as err:
        if err.code == 1005:  # Invalid credentials
            raise InvalidAuth from err
        raise CannotConnect from err
    except Exception as err:
        raise CannotConnect from err

    # Try to get homes to verify the connection works
    try:
        homes = await hass.async_add_executor_job(api.get_homes)
        if not homes:
            raise NoHomes
    except Exception as err:
        raise CannotConnect from err

    return {"title": data[CONF_EMAIL]}


class HomgarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HomGar."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except NoHomes:
            errors["base"] = "no_homes"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(user_input[CONF_EMAIL])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoHomes(HomeAssistantError):
    """Error to indicate no homes were found."""