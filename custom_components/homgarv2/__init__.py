"""The HomGar integration."""
from __future__ import annotations

import logging
from typing import TypeAlias # Added for stable type aliasing

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .api import HomgarApi, HomgarApiException
from .const import (
    CONF_AREA_CODE, 
    CONF_EMAIL, 
    CONF_PASSWORD, 
    DOMAIN, 
    PLATFORMS,
    SERVICE_START_IRRIGATION,
    SERVICE_STOP_IRRIGATION,
    ATTR_DURATION,
    ATTR_ZONE,
    ATTR_DEVICE_ID,
    DEFAULT_IRRIGATION_DURATION,
)
from .coordinator import HomgarDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Re-defined using TypeAlias for compatibility and to satisfy sensor/switch imports
HomgarConfigEntry: TypeAlias = ConfigEntry[HomgarDataUpdateCoordinator]

# Service schemas
SERVICE_START_IRRIGATION_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ID): cv.string,
    vol.Required(ATTR_ZONE): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    vol.Optional(ATTR_DURATION, default=DEFAULT_IRRIGATION_DURATION): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=7200)  # 1 second to 2 hours
    ),
})

SERVICE_STOP_IRRIGATION_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ID): cv.string,
    vol.Required(ATTR_ZONE): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
})


async def async_setup_entry(hass: HomeAssistant, entry: HomgarConfigEntry) -> bool:
    """Set up HomGar from a config entry."""
    _LOGGER.info("[DEBUG] Starting setup for HomGar config entry: %s", entry.entry_id)
    
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    area_code = entry.data[CONF_AREA_CODE]

    api = HomgarApi()
    
    try:
        await hass.async_add_executor_job(api.login, email, password, area_code)
        _LOGGER.info("[DEBUG] HomGar API Login successful for %s", email)
    except HomgarApiException as err:
        _LOGGER.error("Failed to login to HomGar API: %s", err)
        raise ConfigEntryNotReady from err

    coordinator = HomgarDataUpdateCoordinator(
        hass, api, email, password, area_code
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await _async_register_services(hass, coordinator)

    return True


async def _async_register_services(hass: HomeAssistant, coordinator: HomgarDataUpdateCoordinator) -> None:
    """Register services for HomGar integration."""
    
    async def async_start_irrigation(call: ServiceCall) -> None:
        """Handle start irrigation service call."""
        device_id = call.data[ATTR_DEVICE_ID]
        zone = call.data[ATTR_ZONE]
        duration = call.data[ATTR_DURATION]
        
        _LOGGER.info("[DEBUG] [Service Call] START Irrigation: Device=%s, Zone=%s, Duration=%ss", 
                    device_id, zone, duration)
        
        success = await coordinator.async_control_zone(device_id, zone, 1, duration)
        
        if success:
            _LOGGER.info("[DEBUG] [Service Call] START command SENT successfully")
        else:
            _LOGGER.error("[DEBUG] [Service Call] START command FAILED")
    
    async def async_stop_irrigation(call: ServiceCall) -> None:
        """Handle stop irrigation service call."""
        device_id = call.data[ATTR_DEVICE_ID]
        zone = call.data[ATTR_ZONE]
        
        _LOGGER.info("[DEBUG] [Service Call] STOP Irrigation: Device=%s, Zone=%s", device_id, zone)
        
        success = await coordinator.async_control_zone(device_id, zone, 0, 0)
        
        if success:
            _LOGGER.info("[DEBUG] [Service Call] STOP command SENT successfully")
        else:
            _LOGGER.error("[DEBUG] [Service Call] STOP command FAILED")
    
    # Register services
    _LOGGER.debug("[DEBUG] Registering HomGar services")
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_IRRIGATION,
        async_start_irrigation,
        schema=SERVICE_START_IRRIGATION_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_IRRIGATION,
        async_stop_irrigation,
        schema=SERVICE_STOP_IRRIGATION_SCHEMA,
    )


async def async_unload_entry(hass: HomeAssistant, entry: HomgarConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("[DEBUG] Unloading HomGar entry: %s", entry.entry_id)
    coordinator = entry.runtime_data
    
    # Clean up MQTT connections
    await coordinator.async_shutdown()
    
    # Remove services
    hass.services.async_remove(DOMAIN, SERVICE_START_IRRIGATION)
    hass.services.async_remove(DOMAIN, SERVICE_STOP_IRRIGATION)
    
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: HomgarConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("[DEBUG] Reloading HomGar entry: %s", entry.entry_id)
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)