"""Constants for the HomGar integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "homgarv2"

# Configuration
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_AREA_CODE: Final = "area_code"

# Default values
DEFAULT_AREA_CODE: Final = "31"
DEFAULT_UPDATE_INTERVAL: Final = 30  # seconds

# API
API_BASE_URL: Final = "https://region3.homgarus.com"
API_TIMEOUT: Final = 10

# Entity types
ENTITY_TYPE_SENSOR: Final = "sensor"
ENTITY_TYPE_SWITCH: Final = "switch"

# Device types
DEVICE_TYPE_DISPLAY_HUB: Final = "display_hub"
DEVICE_TYPE_SOIL_MOISTURE: Final = "soil_moisture"
DEVICE_TYPE_RAIN_SENSOR: Final = "rain_sensor"
DEVICE_TYPE_AIR_SENSOR: Final = "air_sensor"
DEVICE_TYPE_2_ZONE_TIMER: Final = "2_zone_timer"
DEVICE_TYPE_HTV405FRF: Final = "htv405frf"

# Sensor types
SENSOR_TYPE_TEMPERATURE: Final = "temperature"
SENSOR_TYPE_HUMIDITY: Final = "humidity"
SENSOR_TYPE_PRESSURE: Final = "pressure"
SENSOR_TYPE_SOIL_MOISTURE: Final = "soil_moisture"
SENSOR_TYPE_LIGHT: Final = "light"
SENSOR_TYPE_RAINFALL: Final = "rainfall"
SENSOR_TYPE_ZONE_STATUS: Final = "zone_status"
SENSOR_TYPE_COUNTDOWN_TIMER: Final = "countdown_timer"
SENSOR_TYPE_DURATION_SETTING: Final = "duration_setting"

# Switch types
SWITCH_TYPE_ZONE: Final = "zone"

# Zone statuses
ZONE_STATUS_ON: Final = "on"
ZONE_STATUS_OFF_RECENT: Final = "off_recent"
ZONE_STATUS_OFF_IDLE: Final = "off_idle"

# Model codes
MODEL_CODE_DISPLAY_HUB: Final = 289
MODEL_CODE_SOIL_MOISTURE: Final = 317
MODEL_CODE_RAIN_SENSOR: Final = 87
MODEL_CODE_AIR_SENSOR: Final = 262
MODEL_CODE_2_ZONE_TIMER: Final = 261
MODEL_CODE_HTV405FRF: Final = 38

# Entity icons
ICON_TEMPERATURE: Final = "mdi:thermometer"
ICON_HUMIDITY: Final = "mdi:water-percent"
ICON_PRESSURE: Final = "mdi:gauge"
ICON_SOIL_MOISTURE: Final = "mdi:water-percent"
ICON_LIGHT: Final = "mdi:brightness-6"
ICON_RAINFALL: Final = "mdi:weather-rainy"
ICON_ZONE_STATUS: Final = "mdi:information-outline"
ICON_COUNTDOWN_TIMER: Final = "mdi:timer"
ICON_DURATION_SETTING: Final = "mdi:timer-settings"
ICON_IRRIGATION_ZONE: Final = "mdi:sprinkler"

# NEW: Additional Sensor Icons for HCS014ARF and HCS012ARF
ICON_AIR_SENSOR: Final = "mdi:weather-cloudy"
ICON_RAIN_SENSOR: Final = "mdi:weather-pouring"

# Services
SERVICE_START_IRRIGATION: Final = "start_irrigation"
SERVICE_STOP_IRRIGATION: Final = "stop_irrigation"

# Service parameters
ATTR_DURATION: Final = "duration"
ATTR_ZONE: Final = "zone"
ATTR_DEVICE_ID: Final = "device_id"

# Default service values
DEFAULT_IRRIGATION_DURATION: Final = 600  # 10 minutes in seconds

# Platforms
PLATFORMS = ["sensor", "switch"]