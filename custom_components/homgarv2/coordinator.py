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
SCAN_INTERVAL = timedelta(seconds=30)

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
            # update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
            update_interval=SCAN_INTERVAL,
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
        
        # DEBUG: Track total processed updates since restart to match API sequences
        self._processed_update_count = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint via manual polling."""
        try:
            await self.hass.async_add_executor_job(
                self.api.ensure_logged_in, self.email, self.password, self.area_code
            )

            homes = await self.hass.async_add_executor_job(self.api.get_homes)
            self.homes = homes

            devices = {}
            for home in homes:
                hubs = await self.hass.async_add_executor_job(
                    self.api.get_devices_for_hid, home.hid
                )
                
                for hub in hubs:
                    await self.hass.async_add_executor_job(self.api.get_device_status, hub)
                    devices[f"hub_{hub.mid}"] = hub
                    for subdevice in hub.subdevices:
                        devices[f"device_{subdevice.mid}_{subdevice.address}"] = subdevice

            self.devices = devices

            # LINE 66: This ensures your 30s poll doesn't restart MQTT if it's already alive.
            if not self.api.mqtt_connected:
                await self._setup_mqtt_subscription()
            
            return devices

        except HomgarApiException as err:
            raise UpdateFailed(f"Error communicating with HomGar API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _setup_mqtt_subscription(self) -> None:
        """Set up MQTT subscription for real-time device updates."""
        try:
            if not self.homes or not self.devices:
                return
                
            devices_to_subscribe = []
            hid_list = [home.hid for home in self.homes]
                
            for device_id, device in self.devices.items():
                if device_id.startswith("hub_") and hasattr(device, 'hub_product_key'):
                    if device.hub_product_key:
                        devices_to_subscribe.append({
                            "deviceName": device.hub_device_name or f"MAC-{device.mid}",
                            "mid": str(device.mid),
                            "productKey": device.hub_product_key
                        })
                    
            if devices_to_subscribe and hid_list:
                result = await self.hass.async_add_executor_job(
                    self.api.subscribe_to_device_status, hid_list[0], hid_list, devices_to_subscribe
                )
                
                if result:
                    mqtt_connected = await self.hass.async_add_executor_job(
                        self.api.connect_mqtt, self._on_mqtt_status_update
                    )
                    
                    if mqtt_connected:
                        self.mqtt_connected = self.mqtt_subscribed = True
                        self._start_subscription_renewal_task()
        except Exception as err:
            _LOGGER.error("Error setting up MQTT subscription: %s", err)

    def _on_mqtt_status_update(self, data: dict) -> None:
        """Handle MQTT status update entry point triggered from api.py."""
        self._processed_update_count += 1
        seq = data.get('_seq', 'N/A')
        
        # DEBUG: Match this log to the [MQTT-IN #X] log in api.py
        _LOGGER.info("[DEBUG] [COORDINATOR RECV #%d] Trace-Seq: %s | Data: %s", self._processed_update_count, seq, data)
        
        self.hass.add_job(self._process_mqtt_update(data))

    async def _process_mqtt_update(self, data: dict) -> None:
        """Internal processor for MQTT data with deep state tracing to identify logic failures."""
        try:
            seq = data.get('_seq', 'N/A')
            device_id = data.get('deviceId') or data.get('mid')
            
            if not device_id:
                return
                
            device = None
            for dev_id, dev in self.devices.items():
                if hasattr(dev, 'mid') and str(dev.mid) == str(device_id):
                    device = dev
                    break
                    
            if device and hasattr(device, 'set_device_status'):
                status_payload = data.get('data')
                
                if isinstance(status_payload, dict):
                    # DEBUG: STATE TRACE - BEFORE DATA INJECTION
                    if hasattr(device, 'zones'):
                        _LOGGER.info("[DEBUG] [Proc-Trace #%s] PRE-UPDATE ZONES: %s", seq, device.zones)
                    
                    for s_id, s_val in status_payload.items():
                        device.set_device_status({"id": s_id, "value": str(s_val)})

                    # DEBUG: STATE TRACE - AFTER DATA INJECTION
                    if hasattr(device, 'zones'):
                        _LOGGER.info("[DEBUG] [Proc-Trace #%s] POST-UPDATE ZONES: %s", seq, device.zones)
                    
                    self.async_set_updated_data(self.devices)
                
        except Exception as err:
            _LOGGER.error("Error processing MQTT update: %s", err)

    #def _start_subscription_renewal_task(self):
    #    """Starts the background task to check for token expiration."""
    #    if self._subscription_check_task:
    #        self._subscription_check_task.cancel()
    #    self._subscription_check_task = asyncio.create_task(self._subscription_renewal_loop())

    def _start_subscription_renewal_task(self):
        """Starts the background task to check for token expiration."""
        # Check if a task exists and if it is still running
        if self._subscription_check_task and not self._subscription_check_task.done():
            return

        # Only create a new task if the old one finished or doesn't exist
        self._subscription_check_task = asyncio.create_task(self._subscription_renewal_loop())

    async def _subscription_renewal_loop(self):
        """Periodic loop to ensure MQTT connection stays alive."""
        while self.mqtt_connected:
            try:
                await asyncio.sleep(300)
                needs_renewal = await self.hass.async_add_executor_job(self.api.is_subscription_expired)
                if needs_renewal:
                    if await self.hass.async_add_executor_job(self.api.renew_subscription):
                        await self.hass.async_add_executor_job(self.api.connect_mqtt, self._on_mqtt_status_update)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Renewal loop Error: %s", err)
                await asyncio.sleep(60)

    async def async_control_zone(self, device_id: str, zone_number: int, mode: int, duration: int = 0) -> bool:
        """Passes a UI command down to the device-specific logic."""
        device = self.devices.get(device_id)
        if not device:
            return False
        try:
            return await self.hass.async_add_executor_job(device.control_zone, self.api, zone_number, mode, duration)
        except Exception as err:
            _LOGGER.error("Error controlling zone: %s", err)
            return False

    async def async_shutdown(self) -> None:
        """Graceful cleanup during integration reload or shutdown."""
        if self._subscription_check_task:
            self._subscription_check_task.cancel()
        if self.mqtt_connected:
            await self.hass.async_add_executor_job(self.api.disconnect_mqtt)
            self.mqtt_connected = False