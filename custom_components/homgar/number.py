"""Number platform for HomGar integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo


from .entity import HomgarEntity
from .coordinator import HomgarDataUpdateCoordinator
from .const import DOMAIN, CONF_DURATION, DEFAULT_IRRIGATION_DURATION
from .devices import DiivooWT11W, HTV405FRF


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HomGar number platform."""
    coordinator = config_entry.runtime_data
    
    entities = []
    
    # Check all devices for multi-zone water timers that need duration sliders
    for device_id, device in coordinator.devices.items():
        if isinstance(device, DiivooWT11W):
            # Create a duration number entity for each zone
            for zone_number in [1, 2, 3]:
                entities.append(
                    HomgarZoneDurationNumber(
                        coordinator, device, device_id, zone_number
                    )
                )
        elif isinstance(device, HTV405FRF):
            # Create a duration number entity for each of the 4 HTV405FRF zones
            for zone_number in [1, 2, 3, 4]:
                entities.append(
                    HomgarZoneDurationNumber(
                        coordinator, device, device_id, zone_number
                    )
                )

    if entities:
        async_add_entities(entities)


class HomgarZoneDurationNumber(HomgarEntity, RestoreNumber):
    """Number entity for setting the target duration of a zone."""

    def __init__(self, coordinator, device, device_id, zone):
        """Initialize the number entity."""
        super().__init__(coordinator, device_id, device)
        self.zone = zone
        self._attr_unique_id = f"homgar_duration_{device.did}_{zone}"
        self._attr_name = f"{device.name} Zone {zone} Target Duration"
        
        # We will keep value in minutes for UI user-friendliness
        self._attr_native_min_value = 1
        self._attr_native_max_value = 120
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "min"


    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        
        # Restore the previous value if available, otherwise fetch from config_entry options
        last_number_data = await self.async_get_last_number_data()
        
        if last_number_data and last_number_data.native_value is not None:
            self._attr_native_value = last_number_data.native_value
        else:
            default_sec = self.coordinator.config_entry.options.get(
                CONF_DURATION, DEFAULT_IRRIGATION_DURATION
            )
            self._attr_native_value = default_sec / 60.0

        # Store the restored/initial value in coordinator so switch can access it in seconds
        zone_key = f"{self.device.did}_{self.zone}"
        self.coordinator.target_durations[zone_key] = int(self._attr_native_value * 60)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        
        # Store in coordinator for the switch to read (converted to seconds)
        zone_key = f"{self.device.did}_{self.zone}"
        self.coordinator.target_durations[zone_key] = int(value * 60)
        
        self.async_write_ha_state()
