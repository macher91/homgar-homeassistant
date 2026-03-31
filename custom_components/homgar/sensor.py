"""Support for HomGar sensors."""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfLength,
    LIGHT_LUX,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomgarConfigEntry
from .const import (
    DOMAIN,
    ICON_TEMPERATURE,
    ICON_HUMIDITY,
    ICON_PRESSURE,
    ICON_SOIL_MOISTURE,
    ICON_LIGHT,
    ICON_RAINFALL,
    ICON_ZONE_STATUS,
    ICON_COUNTDOWN_TIMER,
    ICON_DURATION_SETTING,
    ZONE_STATUS_ON,
    ZONE_STATUS_OFF_RECENT,
    ZONE_STATUS_OFF_IDLE,
)
from .coordinator import HomgarDataUpdateCoordinator
from .devices import (
    RainPointDisplayHub,
    RainPointSoilMoistureSensor,
    RainPointRainSensor,
    RainPointAirSensor,
    DiivooWT11W,
    HWG0538WRF,
    HomgarWeatherHub,
    HomgarWeatherStation,
    HomgarIndoorSensor,
    HTV405FRF,
)

from .entity import HomgarEntity

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from datetime import datetime

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS = {
    "temperature": SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_TEMPERATURE,
    ),
    "temp_min": SensorEntityDescription(
        key="temp_min",
        name="Temperature Min",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_TEMPERATURE,
    ),
    "temp_max": SensorEntityDescription(
        key="temp_max",
        name="Temperature Max",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_TEMPERATURE,
    ),

    "humidity": SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_HUMIDITY,
    ),
    "hum_min": SensorEntityDescription(
        key="hum_min",
        name="Humidity Min",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_HUMIDITY,
    ),
    "hum_max": SensorEntityDescription(
        key="hum_max",
        name="Humidity Max",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_HUMIDITY,
    ),

    "pressure": SensorEntityDescription(
        key="pressure",
        name="Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_PRESSURE,
    ),
    "soil_moisture": SensorEntityDescription(
        key="soil_moisture",
        name="Soil Moisture",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_SOIL_MOISTURE,
    ),
    "light": SensorEntityDescription(
        key="light",
        name="Light",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_LIGHT,
    ),
    "rainfall_current": SensorEntityDescription(
        key="rainfall_current",
        name="Rainfall Current",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_RAINFALL,
    ),
    "rainfall_24h": SensorEntityDescription(
        key="rainfall_24h",
        name="Rainfall (24h)",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon=ICON_RAINFALL,
    ),
    "rainfall_7d": SensorEntityDescription(
        key="rainfall_7d",
        name="Rainfall (7d)",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon=ICON_RAINFALL,
    ),
    "rainfall_total": SensorEntityDescription(
        key="rainfall_total",
        name="Rainfall (Total)",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon=ICON_RAINFALL,
    ),

    "zone_status": SensorEntityDescription(
        key="zone_status",
        name="Zone Status",
        icon=ICON_ZONE_STATUS,
    ),
    "countdown_timer": SensorEntityDescription(
        key="countdown_timer",
        name="Countdown Timer",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_COUNTDOWN_TIMER,
    ),
    "duration_setting": SensorEntityDescription(
        key="duration_setting",
        name="Duration Setting",
        icon=ICON_DURATION_SETTING,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HomgarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomGar sensors from a config entry."""
    coordinator = config_entry.runtime_data

    entities = []

    # Create sensors for each device
    for device_id, device in coordinator.devices.items():

        if isinstance(device, RainPointDisplayHub):
            entities.extend([
                HomgarTemperatureSensor(coordinator, device_id, device),
                HomgarHumiditySensor(coordinator, device_id, device),
                HomgarPressureSensor(coordinator, device_id, device),
            ])
        elif isinstance(device, HomgarWeatherStation):
            entities.extend([
                HomgarTemperatureSensor(coordinator, device_id, device),
                HomgarHumiditySensor(coordinator, device_id, device),
                HomgarPressureSensor(coordinator, device_id, device),
            ])
        elif isinstance(device, RainPointSoilMoistureSensor):
            entities.extend([
                HomgarSoilMoistureSensor(coordinator, device_id, device),
                HomgarSoilTemperatureSensor(coordinator, device_id, device),
                HomgarLightSensor(coordinator, device_id, device),
            ])
        elif isinstance(device, RainPointRainSensor):
            entities.extend([
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_current"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_24h"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_7d"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_total"),
            ])
        elif isinstance(device, RainPointAirSensor):
            entities.extend([
                HomgarAirTemperatureSensor(coordinator, device_id, device),
                HomgarAirTemperatureSensor(coordinator, device_id, device, "temp_min"),
                HomgarAirTemperatureSensor(coordinator, device_id, device, "temp_max"),
                HomgarAirHumiditySensor(coordinator, device_id, device),
                HomgarAirHumiditySensor(coordinator, device_id, device, "hum_min"),
                HomgarAirHumiditySensor(coordinator, device_id, device, "hum_max"),
            ])
        elif isinstance(device, HomgarIndoorSensor):
            entities.extend([
                HomgarAirTemperatureSensor(coordinator, device_id, device),
                HomgarAirHumiditySensor(coordinator, device_id, device),
            ])
        elif isinstance(device, DiivooWT11W):
            for zone in [1, 2, 3]:
                entities.extend([
                    HomgarZoneStatusSensor(coordinator, device_id, device, zone),
                    HomgarCountdownTimerSensor(coordinator, device_id, device, zone),
                    HomgarDurationSettingSensor(coordinator, device_id, device, zone),
                ])
        elif isinstance(device, HTV405FRF):
            for zone in [1, 2, 3, 4]:
                entities.extend([
                    HomgarZoneStatusSensor(coordinator, device_id, device, zone),
                ])


    async_add_entities(entities)


class HomgarSensor(CoordinatorEntity, SensorEntity):
    """Base class for HomGar sensors."""

    _attr_force_update = True  # 🔥 C'EST ÇA LA CLÉ

    def __init__(
        self,
        coordinator: HomgarDataUpdateCoordinator,
        device_id: str,
        device: Any,
        description: SensorEntityDescription,
        zone: int | None = None,
    ) -> None:
        super().__init__(coordinator)

        self.device_id = device_id
        self.entity_description = description
        self.zone = zone
        self.device = device
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.did)},
            name=device.name,
            manufacturer="HomGar",
            model=device.model,
        )

        base_uid = f"homgar_{device.did}_{getattr(device, 'sid', device.address)}"


        if zone is not None:
            self._attr_name = f"{device.name} Zone {zone} {description.name}"
            self._attr_unique_id = f"{base_uid}_zone_{zone}_{description.key}"
        else:
            self._attr_name = f"{device.name} {description.name}"
            self._attr_unique_id = f"{base_uid}_{description.key}"

    @property
    def device(self) -> Any | None:
        dev = self.coordinator.data.get(self.device_id)
        _LOGGER.debug(
            "HA DEVICE ACCESS %s -> %s temp=%s",
            self.entity_id,
            self.device_id,
            getattr(dev, "temp_mk_current", None),
        )
        return dev

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return self._attr_device_info

    def _handle_coordinator_update(self) -> None:

        _LOGGER.debug(
            "HA UPDATE %s (%s)",
            self.entity_id,
            self.device_id,
        )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "last_update": datetime.utcnow().isoformat()
        }

class HomgarTemperatureSensor(HomgarSensor):
    """Temperature sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["temperature"],
        )

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        if hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarHumiditySensor(HomgarSensor):
    """Humidity sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["humidity"],
        )

    @property
    def native_value(self) -> int | None:
        """Return the humidity value."""
        return getattr(self.device, 'hum_current', None)


class HomgarPressureSensor(HomgarSensor):
    """Pressure sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["pressure"],
        )

    @property
    def native_value(self) -> float | None:
        """Return the pressure value in hPa."""
        p = getattr(self.device, "press_pa_current", None)
        return p / 10 if p is not None else None


class HomgarSoilMoistureSensor(HomgarSensor):
    """Soil moisture sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["soil_moisture"],
        )

    @property
    def native_value(self) -> int | None:
        """Return the soil moisture value."""
        return getattr(self.device, 'moist_percent_current', None)


class HomgarSoilTemperatureSensor(HomgarSensor):
    """Soil temperature sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["temperature"],
        )

    @property
    def native_value(self) -> float | None:
        """Return the soil temperature value."""
        if hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarLightSensor(HomgarSensor):
    """Light sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(
            coordinator,
            device_id,
            device,
            SENSOR_DESCRIPTIONS["light"],
        )

    @property
    def native_value(self) -> float | None:
        """Return the light value."""
        return getattr(self.device, 'light_lux_current', None)

class HomgarAirTemperatureSensor(HomgarSensor):
    """Air temperature sensor supporting Current, Min, and Max."""
    def __init__(self, coordinator, device_id, device, description_key="temperature"):
        desc = SENSOR_DESCRIPTIONS.get(description_key, SENSOR_DESCRIPTIONS["temperature"])
        # Apply the Air Sensor icon
        new_desc = replace(desc, icon="mdi:weather-cloudy")
        super().__init__(coordinator, device_id, device, new_desc)
        self._desc_key = description_key

    @property
    def native_value(self) -> float | None:
        if not self.device:
            return None
            
        attr = 'temp_mk_current'
        if self._desc_key == "temp_min":
            attr = 'temp_mk_min'
        elif self._desc_key == "temp_max":
            attr = 'temp_mk_max'
        
        val = getattr(self.device, attr, None)
        if val is not None:
            return round(val * 1e-3 - 273.15, 1)
        return None


class HomgarAirHumiditySensor(HomgarSensor):
    """Air humidity sensor supporting Current, Min, and Max."""
    def __init__(self, coordinator, device_id, device, description_key="humidity"):
        desc = SENSOR_DESCRIPTIONS.get(description_key, SENSOR_DESCRIPTIONS["humidity"])
        new_desc = replace(desc, icon="mdi:weather-cloudy")
        super().__init__(coordinator, device_id, device, new_desc)
        self._desc_key = description_key

    @property
    def native_value(self) -> int | None:
        if not self.device:
            return None
            
        attr = 'hum_current'
        if self._desc_key == "hum_min":
            attr = 'hum_min'
        elif self._desc_key == "hum_max":
            attr = 'hum_max'
            
        return getattr(self.device, attr, None)


class HomgarRainfallSensor(HomgarSensor):
    """Rainfall sensor supporting Current, 24h, 7d, and Total."""
    def __init__(self, coordinator, device_id, device, description_key):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS[description_key])
        self._desc_key = description_key

    @property
    def native_value(self) -> float | None:
        if self._desc_key == "rainfall_current":
            return getattr(self.device, 'rain_hour', 0.0)
        if self._desc_key == "rainfall_24h":
            return getattr(self.device, 'rain_24h', 0.0)
        if self._desc_key == "rainfall_7d":
            return getattr(self.device, 'rain_7d', 0.0)
        if self._desc_key == "rainfall_total":
            return getattr(self.device, 'rain_total', 0.0)
        return None



class HomgarZoneStatusSensor(HomgarSensor):
    """Zone status sensor for irrigation timers."""

    def __init__(self, coordinator, device_id, device, zone):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["zone_status"], zone)

    @property
    def native_value(self) -> str | None:
        """Return the zone status."""
        zone_status = self.device.get_zone_status(self.zone)
        if zone_status:
            status_map = {
                ZONE_STATUS_ON: "On",
                ZONE_STATUS_OFF_RECENT: "Off (Recent)",
                ZONE_STATUS_OFF_IDLE: "Off (Idle)",
            }
            return status_map.get(zone_status["status"], zone_status["status"])
        return None


class HomgarCountdownTimerSensor(HomgarSensor):
    """Countdown timer sensor for irrigation timers."""

    def __init__(self, coordinator, device_id, device, zone):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["countdown_timer"], zone)

    @property
    def native_value(self) -> int | None:
        """Return the countdown timer value."""
        return self.device.get_zone_countdown_timer(self.zone)


class HomgarDurationSettingSensor(HomgarSensor):
    """Duration setting sensor for irrigation timers."""

    def __init__(self, coordinator, device_id, device, zone):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["duration_setting"], zone)

    @property
    def native_value(self) -> int | None:
        """Return the duration setting value."""
        return self.device.get_zone_duration_setting(self.zone)
