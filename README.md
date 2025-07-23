# HomGar Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for controlling HomGar irrigation devices, including RainPoint Smart+ sensors and Diivoo timers.

*This project is forked from [Remboooo/homgarapi](https://github.com/Remboooo/homgarapi) and enhanced for Home Assistant integration.*

## Features

- **Device Support**: RainPoint Smart+ sensors and Diivoo WT-11W irrigation timers
- **Sensor Monitoring**: Temperature, humidity, soil moisture, rainfall, and more
- **Zone Control**: Control irrigation zones with customizable durations
- **Real-time Updates**: MQTT-based real-time device status updates
- **Dual Communication**: HTTP API polling with MQTT push notifications for optimal performance
- **Easy Setup**: Configuration through Home Assistant UI

## Supported Devices

### RainPoint Smart+ Devices
- **RainPoint Smart+ Irrigation Display Hub (HWS019WRF-V2)**
  - Temperature, humidity, and pressure sensors
- **RainPoint Smart+ Soil & Moisture Sensor (HCS021FRF)**
  - Soil moisture, temperature, and light sensors
- **RainPoint Smart+ High Precision Rain Sensor (HCS012ARF)**
  - Rainfall measurements (total, hourly, daily)
- **RainPoint Smart+ Outdoor Air Humidity Sensor (HCS014ARF)**
  - Air temperature and humidity sensors
- **RainPoint Smart+ 2-Zone Water Timer (HTV213FRF)**
  - 2-zone irrigation control

### Diivoo Devices
- **Diivoo WT-11W 3-Zone Water Timer**
  - 3-zone irrigation control with advanced status monitoring

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add the repository URL: `https://github.com/macher91/homgar-homeassistant`
6. Select category "Integration"
7. Click "Add"
8. Find "HomGar" in the integrations list and install it
9. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/homgar` folder
2. Copy it to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "HomGar"
4. Enter your HomGar account credentials:
   - **Email**: Your HomGar account email
   - **Password**: Your HomGar account password
   - **Area Code**: Your phone country code (default: 31 for Netherlands)

## Usage

### Sensors

The integration automatically creates sensors for all your devices:

- **Temperature sensors**: `sensor.{device_name}_temperature`
- **Humidity sensors**: `sensor.{device_name}_humidity`
- **Soil moisture sensors**: `sensor.{device_name}_soil_moisture`
- **Rainfall sensors**: `sensor.{device_name}_rainfall`
- **Zone status sensors**: `sensor.{device_name}_zone_1_status`
- **Timer sensors**: `sensor.{device_name}_zone_1_countdown_timer`

### Switches

Irrigation zones are exposed as switches:

- **Zone switches**: `switch.{device_name}_zone_1`

### Automation Examples

#### Turn on irrigation when soil moisture is low

```yaml
automation:
  - alias: "Water plants when soil is dry"
    trigger:
      platform: numeric_state
      entity_id: sensor.garden_soil_moisture
      below: 30
    action:
      service: switch.turn_on
      entity_id: switch.garden_timer_zone_1
      data:
        duration: 1800  # 30 minutes
```

#### Turn off irrigation when it's raining

```yaml
automation:
  - alias: "Stop watering when raining"
    trigger:
      platform: numeric_state
      entity_id: sensor.rain_sensor_hourly_rainfall
      above: 0
    action:
      service: switch.turn_off
      entity_id: switch.garden_timer_zone_1
```

## Device Status

The integration provides detailed status information:

### Zone Status Types
- **On**: Zone is currently active/running
- **Off (Recent)**: Zone was recently turned off
- **Off (Idle)**: Zone is idle (not recently used)

### Available Attributes
- **Connected**: Device connectivity status
- **RSSI**: Signal strength
- **Countdown Timer**: Remaining time for active zones
- **Duration Setting**: Configured irrigation duration

## Communication Methods

This integration uses two communication methods for optimal performance:

### HTTP API Polling
- **Purpose**: Initial device discovery and status fetching
- **Frequency**: Configurable (default: 30 seconds)
- **Use Case**: Fallback when MQTT is unavailable

### MQTT Real-time Updates
- **Purpose**: Instant device status updates
- **Connection**: Alibaba Cloud IoT Platform
- **Benefits**: Immediate response to device changes, reduced API calls
- **Auto-setup**: Automatically configured during integration setup

## Troubleshooting

### Common Issues

1. **Login Failed**: Check your email and password
2. **No Devices Found**: Ensure devices are properly set up in the HomGar app
3. **Connection Issues**: Check your internet connection and HomGar service status
4. **MQTT Connection Failed**: Check firewall settings for outbound connections to port 1883

### Enable Debug Logging

Add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.homgar: debug
```

## Account Setup

**Important**: Logging in via this integration will log you out of the HomGar mobile app. It's recommended to create a separate account:

1. Log out from your main account in the HomGar app
2. Create a new account
3. Log back into your main account
4. Invite the new account from 'Me' → 'Home management' → your home → 'Members'
5. Log into the new account and accept the invite
6. Use the new account credentials for this integration

## Support

- **Issues**: [GitHub Issues](https://github.com/macher91/homgar-homeassistant/issues)
- **Documentation**: [Integration Guide](https://github.com/macher91/homgar-homeassistant)

## Credits

This project is forked from [Remboooo/homgarapi](https://github.com/Remboooo/homgarapi) and enhanced for Home Assistant integration with HACS support.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.