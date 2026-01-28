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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfLength,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomgarConfigEntry
from .const import (
    ICON_TEMPERATURE,
    ICON_HUMIDITY,
    ICON_PRESSURE,
    ICON_SOIL_MOISTURE,
    ICON_ZONE_STATUS,
    ICON_AIR_SENSOR,
    ICON_RAIN_SENSOR,
    ICON_RAINFALL,
)
from .coordinator import HomgarDataUpdateCoordinator
from .devices import (
    RainPointDisplayHub,
    RainPointSoilMoistureSensor,
    RainPointAirSensor,
    RainPointRainSensor,
    HTV405FRF,
)
from .entity import HomgarEntity

_LOGGER = logging.getLogger(__name__)

# Base sensor descriptions
SENSOR_DESCRIPTIONS = {
    "temperature": SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon=ICON_TEMPERATURE,
    ),
    # New Min/Max Temperature Descriptions
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
    # New Min/Max Humidity Descriptions
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
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HomgarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomGar sensors from a config entry."""
    coordinator = config_entry.runtime_data
    _LOGGER.info("[DEBUG] [Sensor Setup] Initializing sensors for %d devices", len(coordinator.devices))

    entities = []

    for device_id, device in coordinator.devices.items():
        if isinstance(device, RainPointDisplayHub):
            # Only add sensors if the specific data exists on the device
            if getattr(device, "temp_mk_current", None) is not None:
                entities.append(HomgarTemperatureSensor(coordinator, device_id, device))
            
            if getattr(device, "hum_current", None) is not None:
                entities.append(HomgarHumiditySensor(coordinator, device_id, device))
                
            if getattr(device, "press_pa_current", None) is not None:
                entities.append(HomgarPressureSensor(coordinator, device_id, device))

        elif isinstance(device, RainPointSoilMoistureSensor):
            entities.append(
                HomgarSoilMoistureSensor(coordinator, device_id, device)
            )
        elif isinstance(device, RainPointAirSensor):
            entities.extend([
                # Temperature Entities (Current, Min, Max)
                HomgarAirTemperatureSensor(coordinator, device_id, device),
                HomgarAirTemperatureSensor(coordinator, device_id, device, "temp_min"),
                HomgarAirTemperatureSensor(coordinator, device_id, device, "temp_max"),
                
                # Humidity Entities (Current, Min, Max)
                HomgarAirHumiditySensor(coordinator, device_id, device),
                HomgarAirHumiditySensor(coordinator, device_id, device, "hum_min"),
                HomgarAirHumiditySensor(coordinator, device_id, device, "hum_max"),
            ])
        elif isinstance(device, RainPointRainSensor):
            entities.extend([
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_current"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_24h"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_7d"),
                HomgarRainfallSensor(coordinator, device_id, device, "rainfall_total"),
            ])
        elif isinstance(device, HTV405FRF):
            for zone in [1, 2, 3, 4]:
                entities.append(
                    HomgarZoneStatusSensor(coordinator, device_id, device, zone)
                )

    _LOGGER.info("[DEBUG] [Sensor Setup] Adding %d sensor entities to HA", len(entities))
    async_add_entities(entities)


class HomgarSensor(HomgarEntity, SensorEntity):
    """Base class for all HomGar sensors."""

    def __init__(
        self,
        coordinator: HomgarDataUpdateCoordinator,
        device_id: str,
        device: Any,
        description: SensorEntityDescription,
        zone: int | None = None,
    ) -> None:
        """Initialize the base sensor."""
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
    """Ambient temperature sensor."""
    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["temperature"])

    @property
    def native_value(self) -> float | None:
        if self.device and hasattr(self.device, 'temp_mk_current') and self.device.temp_mk_current:
            return round(self.device.temp_mk_current * 1e-3 - 273.15, 1)
        return None


class HomgarHumiditySensor(HomgarSensor):
    """Ambient humidity sensor."""
    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["humidity"])

    @property
    def native_value(self) -> int | None:
        return getattr(self.device, 'hum_current', None)


class HomgarPressureSensor(HomgarSensor):
    """Atmospheric pressure sensor."""
    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["pressure"])

    @property
    def native_value(self) -> int | None:
        return getattr(self.device, 'press_pa_current', None)


class HomgarSoilMoistureSensor(HomgarSensor):
    """Soil moisture sensor."""
    def __init__(self, coordinator, device_id, device):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["soil_moisture"])

    @property
    def native_value(self) -> int | None:
        return getattr(self.device, 'moist_percent_current', None)


class HomgarAirTemperatureSensor(HomgarSensor):
    """Air temperature sensor supporting Current, Min, and Max."""
    def __init__(self, coordinator, device_id, device, description_key="temperature"):
        # Use the specific description for Min/Max or default to current
        desc = SENSOR_DESCRIPTIONS.get(description_key, SENSOR_DESCRIPTIONS["temperature"])
        # Apply the Air Sensor icon fix
        new_desc = replace(desc, icon=ICON_AIR_SENSOR)
        super().__init__(coordinator, device_id, device, new_desc)
        self._desc_key = description_key

    @property
    def native_value(self) -> float | None:
        if not self.device:
            return None
            
        # Map the description key to the correct internal variable
        attr = 'temp_mk_current'
        if self._desc_key == "temp_min":
            attr = 'temp_mk_min'
        elif self._desc_key == "temp_max":
            attr = 'temp_mk_max'
        
        val = getattr(self.device, attr, None)
        if val is not None:
            # Convert milli-Kelvin to Celsius rounded to 1 decimal
            return round(val * 1e-3 - 273.15, 1)
        return None


class HomgarAirHumiditySensor(HomgarSensor):
    """Air humidity sensor supporting Current, Min, and Max."""
    def __init__(self, coordinator, device_id, device, description_key="humidity"):
        desc = SENSOR_DESCRIPTIONS.get(description_key, SENSOR_DESCRIPTIONS["humidity"])
        new_desc = replace(desc, icon=ICON_AIR_SENSOR)
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
            return getattr(self.device, 'rain_current', 0.0) # Mapping internal 1h to 'Current'
        if self._desc_key == "rainfall_24h":
            return getattr(self.device, 'rain_24h', 0.0)
        if self._desc_key == "rainfall_7d":
            return getattr(self.device, 'rain_7d', 0.0)
        if self._desc_key == "rainfall_total":
            return getattr(self.device, 'rain_total', 0.0)
        return None


class HomgarZoneStatusSensor(HomgarSensor):
    """Status sensor (On/Off/Idle) for irrigation zones."""
    def __init__(self, coordinator, device_id, device, zone):
        super().__init__(coordinator, device_id, device, SENSOR_DESCRIPTIONS["zone_status"], zone)

    @property
    def native_value(self) -> str | None:
        if self.device and hasattr(self.device, 'get_zone_status_text'):
            return self.device.get_zone_status_text(self.zone)
        return None