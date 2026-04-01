"""DataUpdateCoordinator for HomGar integration."""
from __future__ import annotations

import asyncio
import logging
import time
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
        self.target_durations: dict[str, int] = {}
        self._subscription_check_task = None
        self._mqtt_management_event = asyncio.Event()
        self._mqtt_reconnect_retry_delay = 5

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            # Polling is now a backup to MQTT
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
            
            # Check if any valve is active to adjust polling interval
            any_active = False
            for dev in self.devices.values():
                if hasattr(dev, 'zones'):
                    for zone in dev.zones.values():
                        if zone.get('active'):
                            any_active = True
                            break
                if any_active:
                    break
            
            # Dynamically adjust update interval
            # With MQTT, we can use a much longer fallback interval even when active
            new_interval = timedelta(seconds=300 if any_active else DEFAULT_UPDATE_INTERVAL)
            if self.update_interval != new_interval:
                _LOGGER.debug("Adjusting update interval to %s (any_active=%s)", new_interval, any_active)
                self.update_interval = new_interval

            # Set up MQTT subscription for real-time updates
            if not self.api.mqtt_connected and self.mqtt_subscribed:
                _LOGGER.info("MQTT connection lost, resetting subscription state")
                await self.hass.async_add_executor_job(self.api.disconnect_mqtt)
                self.mqtt_subscribed = False
                self.mqtt_connected = False

            if not self.mqtt_subscribed:
                await self._setup_mqtt_subscription()
            
            self.async_set_updated_data(dict(self.devices))
            _LOGGER.debug("Homgar refresh cycle END")

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
                _LOGGER.debug("Adding home HID: %s, %s", home.hid, home.__dict__)
                
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
                        # Register disconnect callback to trigger reconnection
                        self.api.on_disconnect_callback = self._on_mqtt_disconnect
                        
                        _LOGGER.info("MQTT subscription established for real-time updates")
                        
                        # Start/Update MQTT management task
                        self._start_mqtt_management_task()
                    else:
                        _LOGGER.error("Failed to connect to MQTT broker")
                else:
                    _LOGGER.error("Failed to subscribe to device status updates")
            else:
                _LOGGER.warning("No devices to subscribe to (devices_to_subscribe=%d, hid_list=%d)", 
                               len(devices_to_subscribe), len(hid_list))
                    
        except Exception as err:
            _LOGGER.error("Error setting up MQTT subscription: %s", err)

    def _on_mqtt_disconnect(self, rc: int) -> None:
        """Handle MQTT disconnection."""
        _LOGGER.warning("MQTT disconnected in coordinator (code %s), triggering management loop", rc)
        self.mqtt_connected = False
        # Trigger the management loop to attempt reconnection
        self.hass.loop.call_soon_threadsafe(self._mqtt_management_event.set)

    def _on_mqtt_status_update(self, data: dict) -> None:
        """Handle MQTT status update."""
        try:
            _LOGGER.debug("=== COORDINATOR MQTT STATUS UPDATE ===")
            _LOGGER.debug("Received update data: %s", data)
            
            # Process the MQTT message and update device status
            import asyncio
            asyncio.run_coroutine_threadsafe(self._process_mqtt_update(data), self.hass.loop)
            
        except Exception as err:
            _LOGGER.error("Error processing MQTT status update: %s", err)

    async def _process_mqtt_update(self, data: dict) -> None:
        """Process MQTT update in Home Assistant event loop."""
        try:
            # Find the device that this update is for
            device_id = data.get('deviceId') or data.get('mid') or data.get('did')
            device_name = data.get('deviceName')
            
            if not device_id and not device_name:
                _LOGGER.debug("MQTT data missing both ID and deviceName - payload: %s", data)
                return
                
            # Find matching devices (could be multiple: hub + subdevices)
            matched_devices = []
            
            _LOGGER.debug("Looking for matching devices for mid/did=%s, deviceName=%s", device_id, device_name)
            
            for dev_id, dev in self.devices.items():
                is_match = False
                # 1. Match by mid
                if device_id and hasattr(dev, 'mid') and str(dev.mid) == str(device_id):
                    is_match = True
                # 2. Match by did
                elif device_id and hasattr(dev, 'did') and str(dev.did) == str(device_id):
                    is_match = True
                # 3. Match by deviceName
                elif device_name and hasattr(dev, 'name') and str(dev.name) == str(device_name):
                    is_match = True
                
                if is_match:
                    matched_devices.append((dev_id, dev))
            
            if matched_devices:
                _LOGGER.debug("Found %d matching device(s) for MQTT update", len(matched_devices))
                
                # Extract timestamp from MQTT payload if available
                msg_time = data.get('update', {}).get('time')
                if not msg_time:
                    msg_time = data.get('state', {}).get('time')
                if msg_time:
                    # Convert ms to s
                    msg_time = msg_time / 1000.0

                for dev_id, device in matched_devices:
                    # Create a copy of data to avoid side effects between multiple devices
                    device_data = dict(data)
                    
                    # Special handling for hub-level hex status (D01) that contains data for all zones
                    # We map D01 to the specific device's expected Dxx ID so it accepts the update
                    if (device_data.get('id') == 'D01' and 
                        str(device_data.get('value', '')).startswith('11#') and 
                        hasattr(device, 'address')):
                        
                        target_id = f"D{device.address:02d}"
                        if device_data['id'] != target_id:
                            _LOGGER.debug("Mapping D01 update to %s for device %s", target_id, dev_id)
                            device_data['id'] = target_id
                    
                    # Update device status based on MQTT data
                    if hasattr(device, 'set_device_status'):
                        _LOGGER.debug("Processing MQTT update for %s (%s)", dev_id, type(device).__name__)
                        device.set_device_status(device_data, msg_time=msg_time)
                    else:
                        _LOGGER.warning("Device %s (%s) does not have set_device_status method", 
                                       dev_id, type(device).__name__)
                
                # Trigger coordinator update to notify entities
                self.async_set_updated_data(dict(self.devices))
            else:
                _LOGGER.warning("No matching device found for MQTT update. ID: %s, Name: %s", device_id, device_name)
                
        except Exception as err:
            _LOGGER.error("Error processing MQTT update: %s", err)

    def _start_mqtt_management_task(self):
        """Start the periodic MQTT management task (reconnection and renewal)."""
        if self._subscription_check_task and not self._subscription_check_task.done():
            return
            
        self._subscription_check_task = asyncio.create_task(self._mqtt_management_loop())

    async def _mqtt_management_loop(self):
        """Robust loop to manage MQTT connection and subscription."""
        _LOGGER.debug("Starting MQTT management loop")
        last_heartbeat = 0
        
        while True:
            try:
                current_time = time.time()
                
                # 1. Handle Reconnection if needed
                if not self.mqtt_connected:
                    _LOGGER.info("MQTT not connected, attempting reconnection (retry delay: %ds)", 
                                self._mqtt_reconnect_retry_delay)
                    
                    # Attempt reconnection
                    reconnect_success = await self.hass.async_add_executor_job(
                        self.api.connect_mqtt,
                        self._on_mqtt_status_update
                    )
                    
                    if not reconnect_success:
                        _LOGGER.warning("MQTT reconnection failed, attempting forced credential renewal")
                        renewal_success = await self.hass.async_add_executor_job(
                            self.api.renew_subscription, True
                        )
                        if renewal_success:
                            _LOGGER.info("Credentials renewed successfully, retrying connection")
                            reconnect_success = await self.hass.async_add_executor_job(
                                self.api.connect_mqtt,
                                self._on_mqtt_status_update
                            )

                    if reconnect_success:
                        _LOGGER.info("MQTT reconnection successful")
                        self.mqtt_connected = True
                        self.mqtt_subscribed = True
                        self._mqtt_reconnect_retry_delay = 5 # Reset delay
                        # New connection counts as a fresh heartbeat
                        last_heartbeat = time.time() 
                    else:
                        # Exponential backoff up to 5 minutes
                        backoff = self._mqtt_reconnect_retry_delay
                        self._mqtt_reconnect_retry_delay = min(self._mqtt_reconnect_retry_delay * 2, 300)
                        _LOGGER.warning("MQTT reconnection failing, retrying in %ds", backoff)
                        await asyncio.sleep(backoff)
                        continue 

                # 2. Aliyun Heartbeat (Every 5 minutes / 300s)
                # Aliyun stops routing telemetry if not refreshed via HTTP
                if current_time - last_heartbeat >= 300:
                    _LOGGER.info("Sending periodic Aliyun HTTP heartbeat (subscribeStatus)")
                    success = await self.hass.async_add_executor_job(
                        self.api.renew_subscription, True, False
                    )
                    if success:
                        last_heartbeat = current_time
                        _LOGGER.debug("HTTP Heartbeat successful")
                    else:
                        _LOGGER.warning("HTTP Heartbeat failed, will retry in 30 seconds")
                        # Set to retry sooner than 5m
                        last_heartbeat = current_time - 270 

                # 3. Wait for event or next check cycle
                try:
                    # Wait for disconnect event or just timeout to run the loop again
                    await asyncio.wait_for(self._mqtt_management_event.wait(), timeout=30)
                    self._mqtt_management_event.clear()
                    _LOGGER.debug("MQTT management loop triggered by event")
                except asyncio.TimeoutError:
                    pass
                        
            except asyncio.CancelledError:
                _LOGGER.debug("MQTT management loop cancelled")
                break
            except Exception as err:
                _LOGGER.error("Error in MQTT management loop: %s", err, exc_info=True)
                await asyncio.sleep(60)

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
            _LOGGER.debug(
                "Attempting to control zone %s on device %s (mode=%s, duration=%s)",
                zone_number, device_id, mode, duration
            )
            result_data = await self.hass.async_add_executor_job(
                device.control_zone, self.api, zone_number, mode, duration
            )
            
            # If we got a direct response with data, update the status immediately
            if result_data and isinstance(result_data, dict):
                _LOGGER.debug("Immediate status update from API success response: %s", result_data)
                device.set_device_status(result_data)
                self.async_set_updated_data(dict(self.devices))
            
            return True
        except HomgarApiException as err:
            # Check for Code 4: Already in requested state
            # This contains current data too, so we update and treat as success
            if err.code == 4 and err.data:
                _LOGGER.debug("Device already in requested state (Code 4), updating local state from response.")
                device.set_device_status(err.data)
                self.async_set_updated_data(dict(self.devices))
                return True
                
            _LOGGER.error(
                "Error controlling zone %s on device %s (mode=%s, duration=%s): %s",
                zone_number, device_id, mode, duration, err
            )
            return False
        except Exception as err:
            _LOGGER.error(
                "Unexpected error controlling zone %s on device %s: %s",
                zone_number, device_id, err, exc_info=True
            )
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
