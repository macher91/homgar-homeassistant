"""Support for HomGar sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
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
)
from .entity import HomgarEntity

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
    "humidity": SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_HUMIDITY,
    ),
    "pressure": SensorEntityDescription(
        key="pressure",
        name="Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PA,
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
    "rainfall": SensorEntityDescription(
        key="rainfall",
        name="Rainfall",
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
        elif isinstance(device, RainPointSoilMoistureSensor):
            entities.extend([
                HomgarSoilMoistureSensor(coordinator, device_id, device),
                HomgarSoilTemperatureSensor(coordinator, device_id, device),
                HomgarLightSensor(coordinator, device_id, device),
            ])
        elif isinstance(device, RainPointRainSensor):
            entities.extend([
                HomgarRainfallTotalSensor(coordinator, device_id, device),
                HomgarRainfallHourlySensor(coordinator, device_id, device),
                HomgarRainfallDailySensor(coordinator, device_id, device),
            ])
        elif isinstance(device, RainPointAirSensor):
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

    async_add_entities(entities)


class HomgarSensor(HomgarEntity, SensorEntity):
    """Base class for HomGar sensors."""

    def __init__(
        self,
        coordinator: HomgarDataUpdateCoordinator,
        device_id: str,
        device: Any,
        description: SensorEntityDescription,
        zone: int | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self.zone = zone
        
        if zone is not None:
            self._attr_name = f"{device.name} Zone {zone} {description.name}"
            self._attr_unique_id = f"{device.mid}_{device.address}_zone_{zone}_{description.key}"
        else:
            self._attr_name = f"{device.name} {description.name}"
            self._attr_unique_id = f"{device.mid}_{device.address}_{description.key}"


class HomgarTemperatureSensor(HomgarSensor):
    """Temperature sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["temperature"])

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        if hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarHumiditySensor(HomgarSensor):
    """Humidity sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["humidity"])

    @property
    def native_value(self) -> int | None:
        """Return the humidity value."""
        return getattr(self.device, 'hum_current', None)


class HomgarPressureSensor(HomgarSensor):
    """Pressure sensor for Display Hub."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["pressure"])

    @property
    def native_value(self) -> int | None:
        """Return the pressure value."""
        return getattr(self.device, 'press_pa_current', None)


class HomgarSoilMoistureSensor(HomgarSensor):
    """Soil moisture sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["soil_moisture"])

    @property
    def native_value(self) -> int | None:
        """Return the soil moisture value."""
        return getattr(self.device, 'moist_percent_current', None)


class HomgarSoilTemperatureSensor(HomgarSensor):
    """Soil temperature sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["temperature"])

    @property
    def native_value(self) -> float | None:
        """Return the soil temperature value."""
        if hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarLightSensor(HomgarSensor):
    """Light sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["light"])

    @property
    def native_value(self) -> float | None:
        """Return the light value."""
        return getattr(self.device, 'light_lux_current', None)


class HomgarRainfallTotalSensor(HomgarSensor):
    """Total rainfall sensor."""

    def __init__(self, coordinator, device_id, device):
        desc = SENSOR_DESCRIPTIONS["rainfall"]
        desc.name = "Total Rainfall"
        super().__init__(coordinator, device_id, device, desc)

    @property
    def native_value(self) -> float | None:
        """Return the total rainfall value."""
        return getattr(self.device, 'rainfall_mm_total', None)


class HomgarRainfallHourlySensor(HomgarSensor):
    """Hourly rainfall sensor."""

    def __init__(self, coordinator, device_id, device):
        desc = SENSOR_DESCRIPTIONS["rainfall"]
        desc.name = "Hourly Rainfall"
        super().__init__(coordinator, device_id, device, desc)

    @property
    def native_value(self) -> float | None:
        """Return the hourly rainfall value."""
        return getattr(self.device, 'rainfall_mm_hour', None)


class HomgarRainfallDailySensor(HomgarSensor):
    """Daily rainfall sensor."""

    def __init__(self, coordinator, device_id, device):
        desc = SENSOR_DESCRIPTIONS["rainfall"]
        desc.name = "Daily Rainfall"
        super().__init__(coordinator, device_id, device, desc)

    @property
    def native_value(self) -> float | None:
        """Return the daily rainfall value."""
        return getattr(self.device, 'rainfall_mm_daily', None)


class HomgarAirTemperatureSensor(HomgarSensor):
    """Air temperature sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["temperature"])

    @property
    def native_value(self) -> float | None:
        """Return the air temperature value."""
        if hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarAirHumiditySensor(HomgarSensor):
    """Air humidity sensor."""

    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["humidity"])

    @property
    def native_value(self) -> int | None:
        """Return the air humidity value."""
        return getattr(self.device, 'hum_current', None)


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