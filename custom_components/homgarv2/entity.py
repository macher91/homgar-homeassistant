"""Base entity for HomGar integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomgarDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

class HomgarEntity(CoordinatorEntity[HomgarDataUpdateCoordinator]):
    """Base class for HomGar entities."""

    def __init__(
        self,
        coordinator: HomgarDataUpdateCoordinator,
        device_id: str,
        device: Any,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.mid}_{device.address}")
            },
            name=device.name,
            manufacturer="HomGar",
            model=device.model,
            sw_version=getattr(device, "softVer", None),
        )

    @property
    def device(self) -> Any:
        """
        Return the current device object from the coordinator data.
        This ensures we always access the latest object with fresh MQTT data.
        """
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # DEBUG: Track availability issues
        coord_ok = self.coordinator.last_update_success
        device_present = self.device is not None
        
        if not coord_ok or not device_present:
            _LOGGER.debug("[DEBUG] [Entity Availability] ID=%s, Available=False (CoordSuccess=%s, DevicePresent=%s)", 
                          self.device_id, coord_ok, device_present)
            
        return coord_ok and device_present

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return self._attr_device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}
        
        # Guard against device being None
        if not self.device:
            return attrs

        # Add connection state if available
        if hasattr(self.device, 'connection_state') and self.device.connection_state is not None:
            attrs["connected"] = self.device.connection_state
        
        # Add RSSI if available
        if hasattr(self.device, 'rf_rssi') and self.device.rf_rssi is not None:
            attrs["rssi"] = self.device.rf_rssi
        
        # Add device state if available
        if hasattr(self.device, 'device_state') and self.device.device_state is not None:
            attrs["device_state"] = self.device.device_state
        
        return attrs