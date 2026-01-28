import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Constants for stats parsing
STATS_VALUE_REGEX = re.compile(r'^(\d+)\((\d+)/(\d+)/(\d+)\)')

def _parse_stats_value(s):
    """Parses a HomGar-formatted stats string like '2931(2931/2931/2931)'."""
    if match := STATS_VALUE_REGEX.fullmatch(s):
        return int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    else:
        return None, None, None, None

def _temp_to_mk(f):
    """Convert Fahrenheit (integer * 10) to milli-Kelvin."""
    try:
        return round(1000 * ((int(f) * .1 - 32) * 5 / 9 + 273.15))
    except (ValueError, TypeError):
        return None

def _celsius_to_mk(c):
    """Convert Celsius to milli-Kelvin."""
    try:
        return round((float(c) + 273.15) * 1000)
    except (ValueError, TypeError):
        return None

class HomgarHome:
    """Represents a physical home containing multiple hubs."""
    def __init__(self, hid, name):
        self.hid = hid
        self.name = name

class HomgarDevice:
    """Base class for all HomGar hardware entities."""
    FRIENDLY_DESC = "Unknown HomGar device"

    def __init__(self, model, model_code, name, did, mid, alerts, **kwargs):
        self.model = model
        self.model_code = model_code
        self.name = name
        self.did = did
        self.mid = mid
        self.alerts = alerts
        self.address = None
        self.rf_rssi = None
        self.connection_state = None
        
        if type(self) is HomgarDevice:
            logger.error("SYSTEM ALERT: Unknown device class instantiated. Name='%s', Model='%s'", self.name, self.model)

    def get_device_status_ids(self) -> List[str]:
        """Returns the list of ID strings the API uses for this specific device."""
        return []

    def set_device_status(self, api_obj: dict) -> None:
        """Entry point for applying API/MQTT status packets to this object."""
        status_id = api_obj.get('id')
        if status_id == f"D{self.address:02d}":
            self._parse_status_d_value(api_obj.get('value', ''))
        elif status_id == "connected":
            try:
                self.connection_state = (int(api_obj.get('value', 0)) == 1)
            except:
                pass

    def _parse_status_d_value(self, val: str) -> None:
        """Handles the complex semicolon-delimited status strings."""
        if not val:
            return
        if ';' in val:
            parts = val.split(';')
            if len(parts) >= 2:
                self._parse_general_status_d_value(parts[0])
                self._parse_device_specific_status_d_value(parts[1])
        else:
            self._parse_device_specific_status_d_value(val)

    def _parse_general_status_d_value(self, s: str):
        """Extracts common telemetry like RF RSSI (signal strength)."""
        if ',' in s:
            parts = s.split(',')
            if len(parts) >= 2:
                try:
                    self.rf_rssi = int(parts[1])
                except (ValueError, TypeError):
                    pass

    def _parse_device_specific_status_d_value(self, s: str):
        """Override this in specific device classes."""
        raise NotImplementedError()
class HomgarHubDevice(HomgarDevice):
    """The Gateway device (The Display Hub)."""
    def __init__(self, subdevices, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices = subdevices
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    def _parse_device_specific_status_d_value(self, s):
        pass

class HomgarSubDevice(HomgarDevice):
    """Devices that communicate through a Hub (RF/Bluetooth)."""
    def __init__(self, address, port_number, **kwargs):
        super().__init__(**kwargs)
        self.address = address
        self.port_number = port_number

    def get_device_status_ids(self):
        return [f"D{self.address:02d}", "connected"]

class RainPointAirSensor(HomgarSubDevice):
    """Outdoor/Indoor Air Sensor (HCS014ARF) with Min/Max/Current decoding."""
    MODEL_CODES = [262]
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.temp_mk_min = None
        self.temp_mk_max = None
        self.hum_current = None
        self.hum_min = None
        self.hum_max = None

    def _parse_device_specific_status_d_value(self, s):
        if "10#" in s:
            hex_part = s.split('#')[1]
            try:
                # Little Endian Helper for Temperature
                def parse_t(start):
                    # Swaps bytes (e.g., '5802' -> '0258')
                    flipped = hex_part[start+2:start+4] + hex_part[start:start+2]
                    return _temp_to_mk(int(flipped, 16))

                # TEMPERATURE MAPPING (Offsets 2, 6, 20)
                self.temp_mk_min     = parse_t(2)  # Index 2-5: '5802' -> 15.6C
                self.temp_mk_max     = parse_t(6)  # Index 6-9: '7502' -> 17.2C
                self.temp_mk_current = parse_t(20) # Index 20-23: '6102' -> 16.1C

                # HUMIDITY MAPPING (Offsets 26, 30, 32 based on marker 88)
                pos_88 = hex_part.find('88')
                if pos_88 >= 0:
                    self.hum_current = int(hex_part[pos_88+2:pos_88+4], 16) # '33' -> 51%
                    self.hum_min     = int(hex_part[pos_88+6:pos_88+8], 16) # '31' -> 49%
                    self.hum_max     = int(hex_part[pos_88+8:pos_88+10], 16) # '38' -> 56%
                
                logger.info("[DEBUG] [AIR] %s: T(C:%s Min:%s Max:%s) H(C:%s Min:%s Max:%s)", 
                            self.name, self.temp_mk_current, self.temp_mk_min, 
                            self.temp_mk_max, self.hum_current, self.hum_min, self.hum_max)
            except Exception as e:
                logger.error("Air Sensor parse error: %s", e)

class RainPointRainSensor(HomgarSubDevice):
    """Outdoor Rain Sensor (HCS012ARF) with corrected offsets."""
    MODEL_CODES = [87]
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rain_hour = 0.0
        self.rain_24h = 0.0
        self.rain_7d = 0.0
        self.rain_total = 0.0

    def _parse_device_specific_status_d_value(self, s):
        if "10#" in s:
            hex_part = s.split('#')[1]
            # This line below is what prints the HEX to your logs
            #logger.info("[DEBUG] Raw HEX received: %s", hex_part)
            try:
                # Little Endian Helper: Swaps bytes and divides by 10
                def get_le_val(start):
                    # We need 4 characters (2 bytes)
                    flipped = hex_part[start+2:start+4] + hex_part[start:start+2]
                    return int(flipped, 16) * 0.1

                # Corrected Offsets based on your specific HEX:
                # Index 2: 0000 (Hour) -> 0.0
                # Index 10: 0000 (24h) -> 0.0
                # Index 26: 1202 (7d/Total) -> 53.0
                # Index 36: 1202 (Total/7d) -> 53.0
                
                self.rain_hour   = get_le_val(10)   # Hourly
                self.rain_24h    = get_le_val(18)  # MOVED from 10 to 14
                self.rain_7d     = get_le_val(26)  # 7-Day
                self.rain_total  = get_le_val(36)  # MOVED from 36 to 38 for alignment

                logger.info("[DEBUG] [RAIN] 1h:%.1f, 24h:%.1f, 7d:%.1f, Tot:%.1f", 
                            self.rain_hour, self.rain_24h, self.rain_7d, self.rain_total)
            except Exception as e:
                logger.error("Rain Sensor parse error: %s", e)

class RainPointSoilMoistureSensor(HomgarSubDevice):
    """Soil moisture and temperature sensor (HCS026FRF)."""
    MODEL_CODES = [317]
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.moist_percent_current = None
        self.temp_mk_current = None

    def _parse_device_specific_status_d_value(self, s):
        if not s: return
        if "10#" in s:
            hex_part = s.split('#')[1]
            pos = hex_part.find('DC')
            if pos >= 0 and pos + 8 <= len(hex_part):
                self.moist_percent_current = int(hex_part[pos+6:pos+8], 16)
                logger.info("[DEBUG] [SENSOR UPDATE] %s: Moisture %d%%", self.name, self.moist_percent_current)
            return
        if ',' in s:
            parts = s.split(',')
            if len(parts) >= 2:
                self.temp_mk_current = _temp_to_mk(parts[0])
                self.moist_percent_current = int(parts[1])

class HTV405FRF(HomgarSubDevice):
    """HTV405FRF 4-Zone Smart Water Timer."""
    MODEL_CODES = [38]
    FRIENDLY_DESC = "HTV405FRF 4-Zone Water Timer"

    def __init__(self, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.zones = {i: {"active": False, "status": "off"} for i in [1, 2, 3, 4]}
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key
        self.hw_sequence = "000000"

    def _parse_device_specific_status_d_value(self, s):
        if not s or '#' not in s: return
        hex_data = s.split('#')[1]
        if len(hex_data) >= 8:
            self.hw_sequence = hex_data[2:8]
            logger.info("[DEBUG] [TIMER UPDATE] %s: HW Sequence %s", self.name, self.hw_sequence)
        
        status_map = {'D841': 'on', 'D800': 'off_recent', 'D820': 'off_idle'}
        p_patterns = ['19D8', '1AD8', '1BD8', '1CD8']
        for i, pat in enumerate(p_patterns, 1):
            pos = hex_data.find(pat)
            if pos >= 0 and pos + 6 <= len(hex_data):
                st_code = hex_data[pos+2:pos+6]
                if st_code in status_map:
                    self.zones[i]['active'] = (status_map[st_code] == 'on')
                    self.zones[i]['status'] = status_map[st_code]

    def is_zone_active(self, zone_number: int) -> bool:
        return self.zones.get(zone_number, {}).get('active', False)

    def get_zone_status_text(self, zone_number: int) -> str:
        return self.zones.get(zone_number, {}).get('status', 'unknown')

    def control_zone(self, api, zone_number: int, mode: int, duration: int = 0) -> bool:
        return api.control_device_work_mode(self.hub_device_name, self.hub_product_key, str(self.mid), self.address, zone_number, mode, duration)

class RainPointDisplayHub(HomgarHubDevice):
    """Environmental Display Hub."""
    MODEL_CODES = [289]
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.hum_current = None
        self.press_pa_current = None

    def get_device_status_ids(self):
        return ["connected", "state", "D01"]

    def _parse_device_specific_status_d_value(self, s):
        parts = s.split(',')
        if len(parts) >= 3:
            t_f, *_ = _parse_stats_value(parts[0])
            if t_f: self.temp_mk_current = _temp_to_mk(t_f)
            h, *_ = _parse_stats_value(parts[1])
            if h: self.hum_current = h
            p, *_ = _parse_stats_value(parts[2])
            if p: self.press_pa_current = p

MODEL_CODE_MAPPING = {
    289: RainPointDisplayHub,
    317: RainPointSoilMoistureSensor,
    262: RainPointAirSensor,
    87:  RainPointRainSensor,
    38:  HTV405FRF
}