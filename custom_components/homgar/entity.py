"""Base entity for HomGar integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomgarDataUpdateCoordinator


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
        self.device = device
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
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.device is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return self._attr_device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}
        
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