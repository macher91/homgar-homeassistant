"""Support for HomGar switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomgarConfigEntry
from .const import ICON_IRRIGATION_ZONE
from .coordinator import HomgarDataUpdateCoordinator
from .devices import HTV405FRF
from .entity import HomgarEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HomgarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomGar switches from a config entry."""
    coordinator = config_entry.runtime_data
    _LOGGER.info("[DEBUG] [Switch Setup] Initializing switch entities for %d devices", len(coordinator.devices))

    entities = []

    # Create switches for each zone of supported devices
    for device_id, device in coordinator.devices.items():
        if isinstance(device, HTV405FRF):
            # HTV405FRF is a 4-zone timer
            for zone in [1, 2, 3, 4]:
                entities.append(
                    HomgarZoneSwitch(coordinator, device_id, device, zone)
                )

    _LOGGER.info("[DEBUG] [Switch Setup] Adding %d switch entities to Home Assistant", len(entities))
    async_add_entities(entities)


class HomgarZoneSwitch(HomgarEntity, SwitchEntity):
    """Representation of a HomGar irrigation zone switch."""

    def __init__(
        self,
        coordinator: HomgarDataUpdateCoordinator,
        device_id: str,
        device: Any,
        zone: int,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id, device)
        self.zone = zone
        self._attr_name = f"{device.name} Zone {zone}"
        self._attr_unique_id = f"{device.mid}_{device.address}_zone_{zone}_switch"
        self._attr_icon = ICON_IRRIGATION_ZONE

    @property
    def is_on(self) -> bool:
        """Return True if the zone is currently active (watering)."""
        # DEBUG: Log the exact check from the HA UI
        # This confirms if the dashboard is correctly reading the internal 'active' flag.
        latest_device_data = self.coordinator.data.get(self.device_id)

        if latest_device_data and hasattr(latest_device_data, 'is_zone_active'):
            state = latest_device_data.is_zone_active(self.zone)
            _LOGGER.info("[DEBUG] [Switch UI Check] Device: %s | Zone: %d | is_on: %s", 
                         self.device_id, self.zone, state)
            return state
        
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the zone on via the coordinator."""
        # Default duration if not specified by a service call
        duration = kwargs.get("duration", 600)
        
        _LOGGER.info("[DEBUG] [Switch Action] UI Turning ON: %s | Zone: %d | Duration: %ss", 
                     self.device_id, self.zone, duration)
        
        await self.coordinator.async_control_zone(self.device_id, self.zone, 1, duration)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the zone off via the coordinator."""
        _LOGGER.info("[DEBUG] [Switch Action] UI Turning OFF: %s | Zone: %d", 
                     self.device_id, self.zone)
        
        await self.coordinator.async_control_zone(self.device_id, self.zone, 0, 0)