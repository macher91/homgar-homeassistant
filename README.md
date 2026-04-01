# HomGar Home Assistant Integration

<a href="https://www.buymeacoffee.com/macher"><img src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=macher&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" align="right" /></a>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for **HomGar / RainPoint / Diivoo** devices.

This project is a stabilized and extended version of the HomGar integration, specifically optimized for irrigation timers and weather stations.

---

## 🚀 Key Features

- **Real-Time Irrigation Timers**: Supports second-by-second countdowns for zones using native Home Assistant `TIMESTAMP` sensors.
- **MQTT-Powered Responsiveness**: Uses a virtual observer pattern to capture device status updates instantly via MQTT.
- **Smart Synchronization**: Advanced multi-zone tracking for Diivoo and RainPoint timers with "Last Device Sync" sensors to monitor network health.
- **Weather Station Support**: Full decoding for hierarchical weather hub data (model 257/85/86).

## 🌍 Supported Devices

| Model | Description | Role |
|-------|-------------|------|
| **Diivoo WT-11W** | 3-Zone Smart Water Timer | Irrigation Control |
| **HTV405FRF** | 4-Zone Smart Water Timer | Irrigation Control |
| **257 / 85 / 86** | HomGar Weather Setup | Temp, Humidity, Pressure |
| **HCS026FRF** | Soil Moisture Sensor | Garden Monitoring |
| **HCS012ARF** | Rain Sensor | Precipitation Monitoring |

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
    - `D841` -> Valve is **ON**.
    - `D820` / `D800` -> Valve is **OFF**.
- **`FEFF0F`**: Master Clock marker. The 4 bytes following this are the current device "ticks" (seconds since boot/sync).

#### Byte Order:
Values are encoded in **Little-Endian**. 
Example: `DC05` in hex is `05DC` in decimal (`1500` seconds).

---

## 🤝 Support the Project
If this integration helped you keep your garden green, consider buying me a coffee! ☕

<a href="https://www.buymeacoffee.com/macher"><img src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=macher&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" /></a>

---

*This project is forked and adapted for Home Assistant usage. All product names, logos, and brands are property of their respective owners.*
