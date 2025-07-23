"""DataUpdateCoordinator for HomGar integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HomgarApi, HomgarApiException
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HomgarDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching HomGar data from API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: HomgarApi,
        email: str,
        password: str,
        area_code: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self.api = api
        self.email = email
        self.password = password
        self.area_code = area_code
        self.homes: list = []
        self.devices: dict[str, Any] = {}
        self.mqtt_connected = False
        self.mqtt_subscribed = False
        self._subscription_check_task = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            # Ensure we're logged in
            await self.hass.async_add_executor_job(
                self.api.ensure_logged_in, self.email, self.password, self.area_code
            )

            # Get homes
            homes = await self.hass.async_add_executor_job(self.api.get_homes)
            self.homes = homes

            # Get devices for each home
            devices = {}
            for home in homes:
                hubs = await self.hass.async_add_executor_job(
                    self.api.get_devices_for_hid, home.hid
                )
                
                for hub in hubs:
                    # Get device status
                    await self.hass.async_add_executor_job(
                        self.api.get_device_status, hub
                    )
                    
                    # Store hub
                    devices[f"hub_{hub.mid}"] = hub
                    
                    # Store subdevices
                    for subdevice in hub.subdevices:
                        devices[f"device_{subdevice.mid}_{subdevice.address}"] = subdevice

            self.devices = devices
            
            # Set up MQTT subscription for real-time updates
            if not self.mqtt_subscribed:
                await self._setup_mqtt_subscription()
            
            return devices

        except HomgarApiException as err:
            raise UpdateFailed(f"Error communicating with HomGar API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _setup_mqtt_subscription(self) -> None:
        """Set up MQTT subscription for real-time device updates."""
        _LOGGER.info("Starting MQTT subscription setup")
        try:
            if not self.homes or not self.devices:
                _LOGGER.warning("No homes (%s) or devices (%s) available for MQTT subscription", 
                               len(self.homes) if self.homes else 0,
                               len(self.devices) if self.devices else 0)
                return
                
            # Prepare device list for subscription
            devices_to_subscribe = []
            hid_list = []
            
            for home in self.homes:
                hid_list.append(home.hid)
                _LOGGER.debug("Adding home HID: %s", home.hid)
                
            for device_id, device in self.devices.items():
                _LOGGER.debug("Checking device %s (type: %s)", device_id, type(device).__name__)
                if device_id.startswith("hub_"):
                    _LOGGER.debug("Found hub device: %s", device_id)
                    _LOGGER.debug("Hub device attributes: hub_device_name=%s, hub_product_key=%s", 
                                 getattr(device, 'hub_device_name', 'None'),
                                 getattr(device, 'hub_product_key', 'None'))
                    
                    # Check if device has required attributes for subscription
                    if hasattr(device, 'hub_device_name') and hasattr(device, 'hub_product_key') and device.hub_product_key:
                        device_info = {
                            "deviceName": device.hub_device_name or f"MAC-{device.mid}",
                            "mid": str(device.mid),
                            "productKey": device.hub_product_key
                        }
                        devices_to_subscribe.append(device_info)
                        _LOGGER.debug("Added hub device for subscription: %s", device_info)
                    else:
                        _LOGGER.warning("Hub device %s missing required attributes for subscription: hub_device_name=%s, hub_product_key=%s", 
                                       device_id, 
                                       getattr(device, 'hub_device_name', 'None'),
                                       getattr(device, 'hub_product_key', 'None'))
                    
            if devices_to_subscribe and hid_list:
                primary_hid = hid_list[0]
                _LOGGER.info("Attempting to subscribe to device status for %d devices with primary HID: %s", 
                            len(devices_to_subscribe), primary_hid)
                
                # Subscribe to device status
                subscription_result = await self.hass.async_add_executor_job(
                    self.api.subscribe_to_device_status,
                    primary_hid,
                    hid_list,
                    devices_to_subscribe
                )
                _LOGGER.info("Device status subscription result: %s", subscription_result)
                
                if subscription_result:
                    _LOGGER.info("Attempting to connect to MQTT broker")
                    # Connect to MQTT
                    mqtt_connected = await self.hass.async_add_executor_job(
                        self.api.connect_mqtt,
                        self._on_mqtt_status_update
                    )
                    _LOGGER.info("MQTT connection attempt result: %s", mqtt_connected)
                    
                    if mqtt_connected:
                        self.mqtt_connected = True
                        self.mqtt_subscribed = True
                        _LOGGER.info("MQTT subscription established for real-time updates")
                        
                        # Start subscription renewal task
                        self._start_subscription_renewal_task()
                    else:
                        _LOGGER.error("Failed to connect to MQTT broker")
                else:
                    _LOGGER.error("Failed to subscribe to device status updates")
            else:
                _LOGGER.warning("No devices to subscribe to (devices_to_subscribe=%d, hid_list=%d)", 
                               len(devices_to_subscribe), len(hid_list))
                    
        except Exception as err:
            _LOGGER.error("Error setting up MQTT subscription: %s", err)

    def _on_mqtt_status_update(self, data: dict) -> None:
        """Handle MQTT status update."""
        try:
            _LOGGER.info("=== COORDINATOR MQTT STATUS UPDATE ===")
            _LOGGER.info("Received MQTT status update: %s", data)
            _LOGGER.info("Data type: %s", type(data).__name__)
            
            if isinstance(data, dict):
                _LOGGER.info("Dictionary keys: %s", list(data.keys()))
                for key, value in data.items():
                    _LOGGER.info("  %s: %s (type: %s)", key, str(value)[:100], type(value).__name__)
            
            # Process the MQTT message and update device status
            # This will be called from the MQTT thread, so we need to schedule
            # the update in the Home Assistant event loop
            _LOGGER.info("Scheduling MQTT update processing task")
            asyncio.create_task(self._process_mqtt_update(data))
            _LOGGER.info("=== END COORDINATOR MQTT UPDATE ===")
            
        except Exception as err:
            _LOGGER.error("Error processing MQTT status update: %s", err)

    async def _process_mqtt_update(self, data: dict) -> None:
        """Process MQTT update in Home Assistant event loop."""
        try:
            _LOGGER.info("=== PROCESSING MQTT UPDATE ===")
            _LOGGER.info("Processing MQTT update data: %s", data)
            
            # Find the device that this update is for
            device_id = data.get('deviceId') or data.get('mid')
            _LOGGER.info("Extracted device ID: %s", device_id)
            
            if not device_id:
                _LOGGER.warning("No device ID found in MQTT data - cannot process update")
                _LOGGER.info("Available keys in data: %s", list(data.keys()) if isinstance(data, dict) else "Not a dict")
                return
                
            # Find matching device
            device = None
            _LOGGER.info("Searching for device with ID %s in %d devices", device_id, len(self.devices))
            
            for dev_id, dev in self.devices.items():
                _LOGGER.debug("Checking device %s (mid: %s)", dev_id, getattr(dev, 'mid', 'NO_MID'))
                if hasattr(dev, 'mid') and str(dev.mid) == str(device_id):
                    device = dev
                    _LOGGER.info("Found matching device: %s (%s)", dev_id, type(dev).__name__)
                    break
                    
            if device:
                _LOGGER.info("Device found - updating status")
                _LOGGER.info("Device type: %s", type(device).__name__)
                _LOGGER.info("Device has set_device_status method: %s", hasattr(device, 'set_device_status'))
                
                # Update device status based on MQTT data
                if hasattr(device, 'set_device_status'):
                    _LOGGER.info("Calling set_device_status with data: %s", data)
                    device.set_device_status(data)
                    _LOGGER.info("Device status updated successfully")
                    
                    # Log device state after update
                    if hasattr(device, 'zones'):
                        _LOGGER.info("Device zones after update:")
                        for zone_num, zone_data in device.zones.items():
                            _LOGGER.info("  Zone %d: %s", zone_num, zone_data)
                    
                    # Trigger coordinator update to notify entities
                    _LOGGER.info("Triggering coordinator update to notify entities")
                    self.async_set_updated_data(self.devices)
                    _LOGGER.info("Coordinator update triggered")
                else:
                    _LOGGER.warning("Device does not have set_device_status method")
            else:
                _LOGGER.warning("No matching device found for ID %s", device_id)
                _LOGGER.info("Available devices:")
                for dev_id, dev in self.devices.items():
                    _LOGGER.info("  %s: %s (mid: %s)", dev_id, type(dev).__name__, getattr(dev, 'mid', 'NO_MID'))
                    
            _LOGGER.info("=== END PROCESSING MQTT UPDATE ===")
                
        except Exception as err:
            _LOGGER.error("Error processing MQTT update: %s", err)

    def _start_subscription_renewal_task(self):
        """Start the periodic subscription renewal task."""
        if self._subscription_check_task:
            self._subscription_check_task.cancel()
            
        self._subscription_check_task = asyncio.create_task(self._subscription_renewal_loop())

    async def _subscription_renewal_loop(self):
        """Periodically check and renew MQTT subscription."""
        while self.mqtt_connected:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                if not self.mqtt_connected:
                    break
                    
                # Check if subscription needs renewal
                needs_renewal = await self.hass.async_add_executor_job(
                    self.api.is_subscription_expired
                )
                
                if needs_renewal:
                    _LOGGER.info("MQTT subscription needs renewal")
                    
                    # Renew subscription
                    renewal_success = await self.hass.async_add_executor_job(
                        self.api.renew_subscription
                    )
                    
                    if renewal_success:
                        # Reconnect MQTT with new credentials
                        mqtt_connected = await self.hass.async_add_executor_job(
                            self.api.connect_mqtt,
                            self._on_mqtt_status_update
                        )
                        
                        if mqtt_connected:
                            _LOGGER.info("MQTT reconnected after subscription renewal")
                        else:
                            _LOGGER.error("Failed to reconnect MQTT after subscription renewal")
                            self.mqtt_connected = False
                            break
                    else:
                        _LOGGER.error("Failed to renew MQTT subscription")
                        self.mqtt_connected = False
                        break
                        
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in subscription renewal loop: %s", err)
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    def get_device_by_id(self, device_id: str) -> Any:
        """Get device by ID."""
        return self.devices.get(device_id)

    def get_hub_for_device(self, device_mid: str) -> Any:
        """Get hub for a device."""
        return self.devices.get(f"hub_{device_mid}")

    async def async_control_zone(
        self, device_id: str, zone_number: int, mode: int, duration: int = 0
    ) -> bool:
        """Control a zone on a device."""
        device = self.get_device_by_id(device_id)
        if not device:
            return False

        try:
            await self.hass.async_add_executor_job(
                device.control_zone, self.api, zone_number, mode, duration
            )
            # Request immediate data refresh
            await self.async_request_refresh()
            return True
        except Exception as err:
            _LOGGER.error("Error controlling zone: %s", err)
            return False

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and cleanup resources."""
        try:
            # Cancel subscription renewal task
            if self._subscription_check_task:
                self._subscription_check_task.cancel()
                try:
                    await self._subscription_check_task
                except asyncio.CancelledError:
                    pass
                    
            if self.mqtt_connected:
                await self.hass.async_add_executor_job(self.api.disconnect_mqtt)
                self.mqtt_connected = False
                self.mqtt_subscribed = False
                _LOGGER.info("MQTT connection cleaned up")
        except Exception as err:
            _LOGGER.error("Error during coordinator shutdown: %s", err)
