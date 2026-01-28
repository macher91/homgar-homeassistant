# HomGar Home Assistant Integration v2

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)

A refined Home Assistant integration for the **HomGar / RainPoint** ecosystem. This project is a specialized fork of `Remboooo/homgarapi`, re-engineered for better stability and deeper data extraction from the cloud API.

## ✨ Key Improvements in This Fork

* **Deep Hex Decoding:** Successfully decoded **90% of the raw HEX data** received from the API. This includes advanced sensor metrics and valve states that were previously unavailable.
* **Enhanced Stability:** Re-written MQTT handling to ensure persistent connections without the common "18x duplicate log" or "callback pile-up" issues found in earlier versions.
* **Diagnostic Ready:** Added verbose debug logging that automatically identifies and logs new or unrecognized device codes, making it easier to add support for future hardware.
* **Reliable Polling:** Uses an optimized 30-second HTTP polling mechanism to ensure sensor data (Soil, Air, Rain) is always current, while MQTT handles real-time configuration changes.

---

## 📱 Supported Devices

| Device Type | Model Number | Notes |
| :--- | :--- | :--- |
| **Smart Hub** | `HWG023WBRF-V2` | Required for all sub-devices |
| **Soil Sensor** | `HCS026FRF` | Moisture & Temperature |
| **Air Sensor** | `HCS014ARF` | Temp, Humidity, Min/Max tracking |
| **Rain Sensor** | `HCS012ARF` | Rainfall 24h/7d/Total |
| **4-Zone Valve**| `HTV405FRF` | Individual zone control & timers |

---

## ⚙️ Installation

### Option 1: HACS (Recommended)
1.  Ensure **HACS** is installed and configured in your Home Assistant instance.
2.  Navigate to **HACS** > **Integrations** > **Three dots (top right)** > **Custom Repositories**.
3.  Paste this repository URL and select **Integration** as the category. https://github.com/kitsuneb2/homgar-homeassistant_v2
4.  Search for **HomGar v2**, click **Download**, and restart Home Assistant.

### Option 2: Manual
1.  Download the `custom_components/homgar` folder from this repository.
2.  Copy the folder into your Home Assistant `/config/custom_components/` directory.
3.  Restart Home Assistant.

---

## ⚠️ Important Setup Requirements (Read Before Using)

### 1. Dual-Account Setup (Mandatory)
The HomGar API **does not allow** two simultaneous connections from the same username. If you log in with Home Assistant while your phone app is open, one session will be kicked off immediately.
* **Solution:** Create a **second account** in the HomGar mobile app.
* Invite the second account as a **"Member"** of your Home via the app settings.
* Use the **Member credentials** for this Home Assistant integration.

### 2. MQTT vs. HTTP Polling
* **Status Updates:** Device and sensor statuses (temperature, moisture, etc.) are currently fetched via **30-second HTTP Polling**.
* **Control Commands:** MQTT is utilized for configuration changes and command stability to ensure your valves and timers respond reliably.
* *Note:* Real-time sensor updates via MQTT are currently being researched, but the cloud API currently prioritizes HTTP for state reporting.

---

## 🛠 Troubleshooting & Logs
If you encounter an unsupported device or weird behavior, please enable debug logging in your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.homgar: debug