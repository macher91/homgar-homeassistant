# HomGar Home Assistant Integration

<a href="https://www.buymeacoffee.com/macher"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" align="right" /></a>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for **HomGar / RainPoint / Diivoo** devices.

This project is a stabilized and extended version of the HomGar integration, specifically optimized for irrigation timers and weather stations.

---

## 🚀 Key Features

- **Real-Time Irrigation Timers**: Supports second-by-second countdowns for zones using native Home Assistant `TIMESTAMP` sensors.
- **MQTT-Powered Responsiveness**: Uses a virtual observer pattern to capture device status updates instantly via MQTT.
- **Smart Synchronization**: Advanced multi-zone tracking for Diivoo and RainPoint timers with "Last Device Sync" sensors to monitor network health.
- **Weather Station Support**: Full decoding for hierarchical weather hub data (HG01 + indoor sensor).
- **14 Supported Devices**: Irrigation timers (1–4 zones), weather stations, soil moisture, rain, and air sensors.
- **Zone Duration Sliders**: Per-zone duration number entities for easy irrigation scheduling from the HA dashboard.

---

## 🌍 Supported Devices

### Irrigation Timers

| Model | Model Code | Zones | Description | HA Entities |
|-------|------------|-------|-------------|-------------|
| **Diivoo WT-07W** | 269 | 1 | 1-Zone Smart Water Timer (HTV0535FR) | Switch, Zone Status, Countdown Timer, Duration Setting, Target Duration, Last Sync |
| **Diivoo WT-09W** | 270 | 2 | 2-Zone Smart Water Timer (HTV0537FRF) | Switches, Zone Status, Countdown Timers, Duration Settings, Target Durations, Last Sync |
| **Diivoo WT-11W** | 271 | 3 | 3-Zone Smart Water Timer | Switches, Zone Status, Countdown Timers, Duration Settings, Target Durations, Last Sync |
| **Diivoo WT-13W** | 272 | 4 | 4-Zone Smart Water Timer | Switches, Zone Status, Countdown Timers, Duration Settings, Target Durations, Last Sync |
| **HTV405FRF** | 38 | 4 | 4-Zone Smart Water Timer | Switches, Zone Status, Countdown Timers, Duration Settings, Target Durations |
| **RainPoint 2-Zone Timer** | 261 | 2 | 2-Zone Water Timer | Switches |

### Weather & Environment Sensors

| Model | Model Code | Description | HA Entities |
|-------|------------|-------------|-------------|
| **HomGar Weather Station** | 85 | Outdoor weather station (subdevice of HG01 hub) | Temperature, Humidity, Pressure, Last Sync |
| **HomGar Indoor Sensor** | 86 | Indoor temperature & humidity sensor (subdevice of HG01 hub) | Temperature, Humidity |
| **RainPoint Display Hub** | 264 | Irrigation display hub with built-in weather sensors | Temperature, Humidity, Pressure, Last Sync |
| **HCS026FRF** | 72, 317 | Soil Moisture & Temperature Sensor | Soil Moisture, Soil Temperature, Light |
| **HCS012ARF** | 87 | High Precision Rain Sensor | Rainfall (1h), Rainfall (24h), Rainfall (7d), Rainfall (Total) |
| **HCS014ARF** | 262 | Outdoor Air Humidity & Temperature Sensor | Temperature (Current/Min/Max), Humidity (Current/Min/Max) |

### Hubs

| Model | Model Code | Description | Notes |
|-------|------------|-------------|-------|
| **HomGar Weather Hub (HG01)** | 257 | Gateway hub for weather station & indoor sensor subdevices | No direct entities; manages subdevices |
| **HWG0538WRF** | 256 | Water Timer Hub | Gateway hub for compatible water timer subdevices |

---

## 🔧 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom repositories**
3. Add `https://github.com/macher91/homgar-homeassistant` as a custom repository (category: Integration)
4. Install **HomGar**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/homgar` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

---

## ⚙️ Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **HomGar**
3. Enter your credentials:
   - **Email**: Your HomGar / RainPoint / Diivoo app email
   - **Password**: Your app password
   - **Area Code**: Region code (default: `33` for EU)

### Options

After setup, you can configure:
- **Default irrigation duration**: Default duration in seconds when turning on a zone (default: 600s / 10 minutes)

---

## 🎛️ Services

### `homgar.start_irrigation`

Start irrigation for a specific zone with configurable duration.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `device_id` | string | yes | — | Device ID (e.g., `device_654321_1`) |
| `zone` | number | yes | — | Zone number (1–4 depending on device) |
| `duration` | number | no | 600 | Duration in seconds (max 7200) |

### `homgar.stop_irrigation`

Stop irrigation for a specific zone.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `device_id` | string | yes | Device ID |
| `zone` | number | yes | Zone number |

---

## 🛠️ Debugging & Protocol Analysis

If you have a new HomGar device that isn't fully supported yet, you can help by providing debug logs.

### 1. Enable Debug Logging
Add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.homgar: debug
```

### 2. Identifying Protocol Patterns
Look for log entries starting with `11#`. These contain the raw Hexadecimal status of your device.

#### Common Hex Markers:
- **`B7`**: Countdown timer end-time. The 4 bytes following `B7` represent the "master clock" ticks when the valve will close.
- **`AD`**: Duration setting. The bytes after `AD` indicate the configured watering duration.
- **`D8`**: Status code.
    - `D821` / `D841` -> Valve is **ON**.
    - `D820` -> Valve is **OFF** (recently turned off).
    - `D800` -> Valve is **OFF** (idle).
- **`FEFF0F`**: Master Clock marker. The 4 bytes following this are the current device "ticks" (seconds since boot/sync).

#### Byte Order:
Values are encoded in **Little-Endian**. 
Example: `DC05` in hex is `05DC` in decimal (`1500` seconds).

---

## 🏗️ Architecture

```
homgar/
├── __init__.py          # Integration setup, config entry lifecycle
├── api.py               # HomGar REST API + MQTT client
├── config_flow.py       # Config flow UI for HA setup
├── const.py             # Constants (model codes, entity types, icons)
├── coordinator.py       # DataUpdateCoordinator with MQTT reconnection
├── devices.py           # Device classes (14 models, hex protocol parsers)
├── entity.py            # Base entity class
├── logutil.py           # Logging utilities
├── number.py            # Duration slider number entities
├── sensor.py            # Sensor entities (temp, humidity, rain, zones, timers)
├── switch.py            # Zone switch entities
├── services.yaml        # Service definitions
├── strings.json         # UI strings
└── translations/
    └── en.json          # English translations
```

---

## 🤝 Support the Project
If this integration helped you keep your garden green, consider buying me a coffee! ☕

<a href="https://www.buymeacoffee.com/macher"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" /></a>

---

*This project is forked and adapted for Home Assistant usage. All product names, logos, and brands are property of their respective owners.*
