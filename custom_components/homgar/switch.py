"""Support for HomGar switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomgarConfigEntry
from .const import ICON_IRRIGATION_ZONE, ZONE_STATUS_ON
from .coordinator import HomgarDataUpdateCoordinator
from .devices import DiivooWT11W, RainPoint2ZoneTimer, HWG0538WRF
from .entity import HomgarEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HomgarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomGar switches from a config entry."""
    coordinator = config_entry.runtime_data

    entities = []

    # Create switches for each irrigation zone
    for device_id, device in coordinator.devices.items():
        if isinstance(device, DiivooWT11W):
            for zone in [1, 2, 3]:
                entities.append(
                    HomgarZoneSwitch(coordinator, device_id, device, zone)
                )
        elif isinstance(device, RainPoint2ZoneTimer):
            for zone in [1, 2]:
                entities.append(
                    HomgarZoneSwitch(coordinator, device_id, device, zone)
                )

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
        """Return True if the zone is on."""
        if isinstance(self.device, DiivooWT11W):
            return self.device.is_zone_active(self.zone)
        # For other timer types, implement as needed
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = super().extra_state_attributes
        
        if isinstance(self.device, DiivooWT11W):
            attrs.update({
                "zone_status": self.device.get_zone_status_text(self.zone),
                "countdown_timer": self.device.get_zone_countdown_timer(self.zone),
                "duration_setting": self.device.get_zone_duration_setting(self.zone),
            })
        
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the zone on."""
        # Default duration can be customized or made configurable
        duration = kwargs.get("duration", 600)  # 10 minutes default
        
        success = await self.coordinator.async_control_zone(
            self.device_id, self.zone, 1, duration
        )
        
        if not success:
            _LOGGER.error("Failed to turn on zone %s for device %s", self.zone, self.device.name)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the zone off."""
        success = await self.coordinator.async_control_zone(
            self.device_id, self.zone, 0, 0
        )
        
        if not success:
            _LOGGER.error("Failed to turn off zone %s for device %s", self.zone, self.device.name)