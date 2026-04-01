import re
import logging
from typing import List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


STATS_VALUE_REGEX = re.compile(r'^(\d+)\((\d+)/(\d+)/(\d+)\)')

def _safe_int(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split("(")[0]
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_stats_value(s):
    if match := STATS_VALUE_REGEX.fullmatch(s):
        return int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    else:
        return None, None, None, None


def _temp_to_mk(f):
    return round(1000 * ((int(f) * .1 - 32) * 5 / 9 + 273.15))


class HomgarHome:
    """
    Represents a home in Homgar.
    A home can have a number of hubs, each of which can contain sensors/controllers (subdevices).
    """
    def __init__(self, hid, name):
        self.hid = hid
        self.name = name


class HomgarDevice:
    """
    Base class for Homgar devices; both hubs and subdevices.
    Each device has a model (name and code), name, some identifiers and may have alerts.
    """

    FRIENDLY_DESC = "Unknown HomGar device"

    def __init__(self, model, model_code, name, did, mid, alerts, **kwargs):
        self.model = model
        self.model_code = model_code
        self.name = name
        self.did = did  # the unique device identifier of this device itself
        self.mid = mid  # the unique identifier of the sensor network
        self.alerts = alerts
        self.last_sync_time = None

        self.address = None
        self.rf_rssi = None

    def __str__(self):
        return f"{self.FRIENDLY_DESC} \"{self.name}\" (DID {self.did})"

    def get_device_status_ids(self) -> List[str]:
        """
        The response for /app/device/getDeviceStatus contains a subDeviceStatus for each of the subdevices.
        This function returns which IDs in the subDeviceStatus apply to this device.
        Usually this is just Dxx where xx is the device address, but the hub has some additional special keys.
        set_device_status() will be called on this object for all subDeviceStatus entries matching any of the
        return IDs.
        :return: The subDeviceStatus this device should listen to.
        """
        return []

    def set_device_status(self, api_obj: dict, msg_time: float = None) -> None:
        """
        Update the device status from an API response (poll, MQTT, or command feedback).
        """
        attr_id = api_obj.get('id')
        value = api_obj.get('value') or api_obj.get('state')
        
        if not value:
            return

        # Update last sync time whenever we get a valid value
        self.last_sync_time = msg_time if msg_time else datetime.now().timestamp()

        # Handle direct state response (no 'id' field) or matching 'id' field
        if attr_id == f"D{self.address:02d}" or (not attr_id and value.startswith('11#')):
            self._parse_status_d_value(value, msg_time=msg_time)

    def _parse_status_d_value(self, val: str, msg_time: float = None) -> None:
        """
        Parses status value. Handles both 'general;specific' (poll/mqtt) and 'specific' (direct command response).
        """
        if ';' in val:
            general_str, specific_str = val.split(';')
            self._parse_general_status_d_value(general_str)
            self._parse_device_specific_status_d_value(specific_str, msg_time=msg_time)
        elif val.startswith('11#'):
            # Direct status response (just the hex part)
            self._parse_device_specific_status_d_value(val, msg_time=msg_time)

    def _parse_general_status_d_value(self, s: str):
        """
        Parses the part of a $.data.subDeviceStatus[x].value field before the ';' character,
        which has the same format for all subdevices. It has three ','-separated fields. The first and last fields
        are always '1' in my case, I presume it's to do with battery state / connection state.
        The second field is the RSSI in dBm.
        :param s: The value to parse and apply
        """
        unknown_1, rf_rssi, unknown_2 = s.split(',')
        self.rf_rssi = int(rf_rssi)

    def _parse_device_specific_status_d_value(self, s: str, msg_time: float = None):
        """
        Parses the part of a $.data.subDeviceStatus[x].value field after the ';' character,
        which is in a device-specific format.
        Should update the device state.
        :param s: The value to parse and apply
        """
        raise NotImplementedError()


class HomgarHubDevice(HomgarDevice):
    """
    A hub acts as a gateway for sensors and actuators (subdevices).
    A home contains an arbitrary number of hubs, each of which contains an arbitrary number of subdevices.
    """
    def __init__(self, subdevices=None, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices = subdevices or []
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    def __str__(self):
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        pass


class HomgarSubDevice(HomgarDevice):
    """
    A subdevice is a device that is associated with a hub.
    It can be a sensor or an actuator.
    """
    def __init__(self, address, port_number, **kwargs):
        super().__init__(**kwargs)
        self.address = address  # device address within the sensor network
        self.port_number = port_number  # the number of ports on the device, e.g. 2 for the 2-zone water timer

    def __str__(self):
        return f"{super().__str__()} at address {self.address}"

    def get_device_status_ids(self):
        return [f"D{self.address:02d}"]

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        pass


class RainPointDisplayHub(HomgarHubDevice):
    MODEL_CODES = [264]
    FRIENDLY_DESC = "Irrigation Display Hub"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wifi_rssi = None
        self.battery_state = None
        self.connected = None

        self.temp_mk_current = None
        self.temp_mk_daily_max = None
        self.temp_mk_daily_min = None
        self.temp_trend = None
        self.hum_current = None
        self.hum_daily_max = None
        self.hum_daily_min = None
        self.hum_trend = None
        self.press_pa_current = None
        self.press_pa_daily_max = None
        self.press_pa_daily_min = None
        self.press_trend = None

    def get_device_status_ids(self):
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj, msg_time=None):
        attr_id = api_obj.get('id')
        value = api_obj.get('value') or api_obj.get('state')
 
        if attr_id == "state":
            try:
                self.battery_state, self.wifi_rssi = [int(s) for s in value.split(',')]
            except Exception:
                pass
        elif attr_id == "connected":
            self.connected = int(value) == 1
        else:
            super().set_device_status(api_obj, msg_time=msg_time)

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        """
        Observed example value:
        781(781/723/1),52(64/50/1),P=10213(10222/10205/1),

        Deduced meaning:
        temp[.1F](day-max/day-min/trend?),humidity[%](day-max/day-min/trend?),P=pressure[Pa](day-max/day-min/trend?),
        """
        temp_str, hum_str, press_str, *_ = s.split(',')
        self.temp_mk_current, self.temp_mk_daily_max, self.temp_mk_daily_min, self.temp_trend = [_temp_to_mk(v) for v in _parse_stats_value(temp_str)]
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)
        self.press_pa_current, self.press_pa_daily_max, self.press_pa_daily_min, self.press_trend = _parse_stats_value(press_str[2:])

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3:.1f}K / {self.hum_current}% / {self.press_pa_current}Pa"
        return s


class RainPointSoilMoistureSensor(HomgarSubDevice):
    """Soil moisture and temperature sensor (HCS026FRF)."""
    MODEL_CODES = [72, 317]
    FRIENDLY_DESC = "Soil Moisture Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.moist_percent_current = None
        self.temp_mk_current = None

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        if not s: return
        if "10#" in s:
            hex_part = s.split('#')[1]
            pos = hex_part.find('DC')
            if pos >= 0 and pos + 8 <= len(hex_part):
                self.moist_percent_current = int(hex_part[pos+6:pos+8], 16)
                logger.debug("[DEBUG] [SENSOR UPDATE] %s: Moisture %d%%", self.name, self.moist_percent_current)
            return
        if ',' in s:
            parts = s.split(',')
            if len(parts) >= 2:
                self.temp_mk_current = _temp_to_mk(parts[0])
                self.moist_percent_current = int(parts[1])

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3-273.15:.1f}°C / {self.moist_percent_current}%"
        return s


class RainPointRainSensor(HomgarSubDevice):
    """Outdoor Rain Sensor (HCS012ARF) with corrected offsets."""
    MODEL_CODES = [87]
    FRIENDLY_DESC = "High Precision Rain Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rain_hour = 0.0
        self.rain_24h = 0.0
        self.rain_7d = 0.0
        self.rain_total = 0.0

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        if "10#" in s:
            hex_part = s.split('#')[1]
            try:
                # Little Endian Helper: Swaps bytes and divides by 10
                def get_le_val(start):
                    # We need 4 characters (2 bytes)
                    flipped = hex_part[start+2:start+4] + hex_part[start:start+2]
                    return int(flipped, 16) * 0.1

                self.rain_hour   = get_le_val(10)   # Hourly
                self.rain_24h    = get_le_val(18)
                self.rain_7d     = get_le_val(26)
                self.rain_total  = get_le_val(36)
                
                logger.debug("[DEBUG] [RAIN] 1h:%.1f, 24h:%.1f, 7d:%.1f, Tot:%.1f", 
                            self.rain_hour, self.rain_24h, self.rain_7d, self.rain_total)
            except Exception as e:
                logger.error("Rain Sensor parse error: %s", e)

    def __str__(self):
        s = super().__str__()
        if self.rain_total:
            s += f": {self.rain_total}mm total / {self.rain_hour}mm 1h / {self.rain_24h}mm 24h / {self.rain_7d}mm 7days"
        return s


class RainPointAirSensor(HomgarSubDevice):
    """Outdoor/Indoor Air Sensor (HCS014ARF) with Min/Max/Current decoding."""
    MODEL_CODES = [262]
    FRIENDLY_DESC = "Outdoor Air Humidity Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.temp_mk_min = None
        self.temp_mk_max = None
        self.hum_current = None
        self.hum_min = None
        self.hum_max = None

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        if "10#" in s:
            hex_part = s.split('#')[1]
            try:
                # Little Endian Helper for Temperature
                def parse_t(start):
                    flipped = hex_part[start+2:start+4] + hex_part[start:start+2]
                    return _temp_to_mk(int(flipped, 16))

                self.temp_mk_min     = parse_t(2)
                self.temp_mk_max     = parse_t(6)
                self.temp_mk_current = parse_t(20)

                pos_88 = hex_part.find('88')
                if pos_88 >= 0:
                    self.hum_current = int(hex_part[pos_88+2:pos_88+4], 16)
                    self.hum_min     = int(hex_part[pos_88+6:pos_88+8], 16)
                    self.hum_max     = int(hex_part[pos_88+8:pos_88+10], 16)
                
                logger.debug("[DEBUG] [AIR] %s: T(C:%s Min:%s Max:%s) H(C:%s Min:%s Max:%s)", 
                            self.name, self.temp_mk_current, self.temp_mk_min, 
                            self.temp_mk_max, self.hum_current, self.hum_min, self.hum_max)
            except Exception as e:
                logger.error("Air Sensor parse error: %s", e)
        elif ',' in s:
            parts = s.split(',')
            if len(parts) >= 2:
                temp_str, hum_str, *_ = parts
                self.temp_mk_current, self.temp_mk_daily_max, self.temp_mk_daily_min, self.temp_trend = [_temp_to_mk(v) for v in _parse_stats_value(temp_str)]
                self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3-273.15:.1f}°C / {self.hum_current}%"
        return s


class RainPoint2ZoneTimer(HomgarSubDevice):
    MODEL_CODES = [261]
    FRIENDLY_DESC = "2-Zone Water Timer"

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        pass


class HTV405FRF(HomgarSubDevice):
    """HTV405FRF 4-Zone Smart Water Timer."""
    MODEL_CODES = [38]
    FRIENDLY_DESC = "HTV405FRF 4-Zone Water Timer"

    def __init__(self, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.zones = {i: {"active": False, "status": "off", "countdown_timer": 0, "duration_setting": 0} for i in [1, 2, 3, 4]}
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key
        self.hw_sequence = "000000"

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        if not s or '#' not in s: return
        hex_data = s.split('#')[1]

        # Update sync time if valid irrigation markers are found
        # 19D8/1AD8/1BD8/1CD8 = Zone Status, 25AD/26AD/27AD/28AD = Zone Durations
        sync_markers = ['19D8', '1AD8', '1BD8', '1CD8', '25AD', '26AD', '27AD', '28AD']
        if any(marker in hex_data for marker in sync_markers) and msg_time:
            self.last_sync_time = msg_time

        if len(hex_data) >= 8:
            self.hw_sequence = hex_data[2:8]
        
        status_map = {'D841': 'on', 'D800': 'off_recent', 'D820': 'off_idle'}
        p_patterns = ['19D8', '1AD8', '1BD8', '1CD8']
        for i, pat in enumerate(p_patterns, 1):
            pos = hex_data.find(pat)
            if pos >= 0 and pos + 6 <= len(hex_data):
                st_code = hex_data[pos+2:pos+6]
                if st_code in status_map:
                    self.zones[i]['active'] = (status_map[st_code] == 'on')
                    self.zones[i]['status'] = status_map[st_code]

        # Get current device ticks (master clock) from FEFF0F pattern
        current_ticks = 0
        pos_clk = hex_data.find('FEFF0F')
        if pos_clk >= 0 and pos_clk + 14 <= len(hex_data):
            clk_hex = hex_data[pos_clk+6:pos_clk+14]
            try:
                current_ticks = int.from_bytes(bytes.fromhex(clk_hex), "little")
            except Exception:
                pass

        # Parse Countdown Timers (21B7, 22B7, 23B7, 24B7)
        countdown_patterns = ['21B7', '22B7', '23B7', '24B7']
        for i, pat in enumerate(countdown_patterns, 1):
            pos = hex_data.find(pat)
            if pos >= 0 and pos + 12 <= len(hex_data):
                timer_hex = hex_data[pos+4:pos+12]
                try:
                    # Value is absolute end-time ticks
                    end_ticks = int.from_bytes(bytes.fromhex(timer_hex), "little")
                    if end_ticks > current_ticks > 0:
                        self.zones[i]['countdown_timer'] = end_ticks - current_ticks
                    else:
                        self.zones[i]['countdown_timer'] = 0
                        # Proactive auto-off: if timer is 0, zone must be off
                        if self.zones[i]['active']:
                            logger.debug("Zone %d timer expired, forcing active=False", i)
                            self.zones[i]['active'] = False
                            self.zones[i]['status'] = 'off_idle'
                except Exception:
                    self.zones[i]['countdown_timer'] = 0

        # Parse Duration Settings (25AD, 26AD, 27AD, 28AD)
        duration_patterns = ['25AD', '26AD', '27AD', '28AD']
        for i, pat in enumerate(duration_patterns, 1):
            pos = hex_data.find(pat)
            if pos >= 0 and pos + 8 <= len(hex_data):
                dur_hex = hex_data[pos+4:pos+8]
                try:
                    dur_val = int.from_bytes(bytes.fromhex(dur_hex), "little")
                    self.zones[i]['duration_setting'] = dur_val
                except Exception:
                    self.zones[i]['duration_setting'] = 0

    def get_zone_status(self, zone_number: int) -> dict | None:
        return self.zones.get(zone_number)

    def get_zone_countdown_timer(self, zone_number: int) -> int:
        zone = self.get_zone_status(zone_number)
        return zone['countdown_timer'] if zone else 0

    def get_zone_duration_setting(self, zone_number: int) -> int:
        zone = self.get_zone_status(zone_number)
        return zone['duration_setting'] if zone else 0

    def is_zone_active(self, zone_number: int) -> bool:

        return self.zones.get(zone_number, {}).get('active', False)

    def get_zone_status_text(self, zone_number: int) -> str:
        return self.zones.get(zone_number, {}).get('status', 'unknown')

    def control_zone(self, api, zone_number: int, mode: int, duration: int = 0) -> bool:
        return api.control_device_work_mode(self.hub_device_name, self.hub_product_key, str(self.mid), self.address, zone_number, mode, duration)



class DiivooWT11W(HomgarSubDevice):
    MODEL_CODES = [271]
    FRIENDLY_DESC = "Diivoo WT-11W 3-Zone Water Timer"

    def __init__(self, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.zones = {
            1: {"active": False, "status": "off_idle", "countdown_timer": 0, "countdown_end_time": None, "duration_setting": 0},
            2: {"active": False, "status": "off_idle", "countdown_timer": 0, "countdown_end_time": None, "duration_setting": 0},
            3: {"active": False, "status": "off_idle", "countdown_timer": 0, "countdown_end_time": None, "duration_setting": 0}
        }
        self.connection_state = None
        self.device_state = None
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        """
        Parses the device-specific status for Diivoo WT-11W.
        
        Status format: 11#[hex_data]
        
        Hex data structure:
        - 17 E19F00 - sequence
        - 19 D821 - port 1 status (D821=On, D820=Off Recent, D800=Off Idle)
        - 1A D800 - port 2 status 
        - 1B D800 - port 3 status
        - 1D 201E - unknown
        - 20 1F20 - unknown 
        - 18 DC01 - unknown
        - 21 B79AE7DE15 - Port 1: Countdown Timer
        - 22 B700000000 - Port 2: Countdown Timer
        - 23 B700000000 - Port 3: Countdown Timer
        - 25 ADDC05 - Port 1: Duration Setting
        - 26 AD0000 - Port 2: Duration Setting
        - 27 AD0000 - Port 3: Duration Setting
        """
        logger.debug("--- PARSING DIIVOO HEX STATUS ---")
        
        self.raw_status = s
        
        if '#' not in s:
            return
            
        parts = s.split('#')
        if len(parts) < 2:
            return
            
        hex_data = parts[1]
        self.hex_status_data = hex_data
        
        logger.debug("Hex data: %s", hex_data)
        
        # Parse the hex data according to the documented format
        try:
            self._parse_hex_status_data(hex_data, msg_time=msg_time)
        except Exception as e:
            logger.error("Error parsing hex data: %s", e)
            # If parsing fails, store raw data for debugging
            self.parse_error = str(e)
    
    def _parse_hex_status_data(self, hex_data, msg_time=None):
        """
        Parse the hex-encoded status data into structured information.
        """
        if len(hex_data) < 50:
            return
            
        # Note: last_sync_time is now handled in the base class set_device_status

        # Parse sequence (first 6 characters after the initial bytes)
        if len(hex_data) >= 8:
            self.sequence = hex_data[2:8]
        
        # Get current device ticks (master clock) from FEFF0F pattern
        current_ticks = 0
        pos_clk = hex_data.find('FEFF0F')
        if pos_clk >= 0 and pos_clk + 14 <= len(hex_data):
            clk_hex = hex_data[pos_clk+6:pos_clk+14]
            try:
                current_ticks = int.from_bytes(bytes.fromhex(clk_hex), "little")
            except Exception:
                pass

        # Parse port statuses
        self._parse_port_statuses_precise(hex_data)
        self._parse_countdown_timers_precise(hex_data, current_ticks)
        self._parse_duration_settings_precise(hex_data)
    
    def _parse_port_statuses_precise(self, hex_data):
        """
        Parse port statuses using the documented byte positions.
        Looking for patterns like:
        - 19D821 - port 1 status (on)
        - 1AD820 - port 2 status (off_recent)
        - 1BD800 - port 3 status (off_idle)
        """
        status_map = {
            'D821': 'on',
            'D820': 'off_recent',
            'D800': 'off_idle'
        }
        
        port_patterns = ['19D8', '1AD8', '1BD8']  # Port 1, 2, 3 patterns
        
        for port_num, pattern in enumerate(port_patterns, 1):
            pattern_pos = hex_data.find(pattern)
            
            if pattern_pos >= 0 and pattern_pos + 6 <= len(hex_data):
                full_pattern = hex_data[pattern_pos:pattern_pos + 6]
                status_hex = full_pattern[2:]
                
                if status_hex in status_map:
                    self.zones[port_num]['active'] = status_map[status_hex] == 'on'
                    self.zones[port_num]['status'] = status_map[status_hex]
                    logger.debug("Port %d status updated: %s", port_num, status_map[status_hex])
                else:
                    logger.warning("Port %d unknown status hex: %s", port_num, status_hex)
    
    def _parse_countdown_timers_precise(self, hex_data, current_ticks, msg_time=None):
        """
        Parse countdown timers for each port.
        Looking for patterns like:
        - 21B79AE7DE15 - Port 1 countdown timer
        - 22B700000000 - Port 2 countdown timer
        - 23B700000000 - Port 3 countdown timer
        """
        timer_patterns = ['21B7', '22B7', '23B7']
        
        for port_num, pattern in enumerate(timer_patterns, 1):
            pattern_pos = hex_data.find(pattern)
            
            if pattern_pos >= 0 and pattern_pos + 12 <= len(hex_data):
                timer_hex = hex_data[pattern_pos:pattern_pos + 12]
                if timer_hex.startswith(pattern):
                    timer_value_hex = timer_hex[4:]
                    try:
                        timer_bytes = bytes.fromhex(timer_value_hex)
                        # Value is absolute end-time ticks
                        end_ticks = int.from_bytes(timer_bytes, "little")
                        
                        if end_ticks > current_ticks > 0:
                            # Ticks for Diivoo WT-11W are 1:1 with seconds
                            rem_s = end_ticks - current_ticks
                        else:
                            rem_s = 0
                            # Proactive auto-off: if timer is 0, zone must be off
                            if self.zones[port_num]['active']:
                                logger.debug("Port %d timer expired, forcing active=False", port_num)
                                self.zones[port_num]['active'] = False
                                self.zones[port_num]['status'] = 'off_idle'
                            
                        self.zones[port_num]['countdown_timer'] = rem_s
                        if rem_s > 0:
                            # Use msg_time if available, otherwise current local time
                            base_time = msg_time if msg_time else datetime.now().timestamp()
                            new_end_time = base_time + rem_s
                            
                            # Stabilize end_time: only update if it shifts by more than 10s
                            # This prevents the UI timer from "jumping" due to MQTT latency
                            old_end_time = self.zones[port_num].get('countdown_end_time')
                            if not old_end_time or abs(new_end_time - old_end_time) > 10:
                                self.zones[port_num]['countdown_end_time'] = new_end_time
                        else:
                            self.zones[port_num]['countdown_end_time'] = None

                        logger.debug("Port %d timer updated: %d seconds", port_num, rem_s)
                    except ValueError as e:
                        logger.debug("Port %d timer conversion error: %s", port_num, e)
                        self.zones[port_num]['countdown_timer'] = 0
    
    def _parse_duration_settings_precise(self, hex_data):
        """
        Parse duration settings for each port.
        Looking for patterns like:
        - 25ADDC05 - Port 1 duration setting
        - 26AD0000 - Port 2 duration setting
        - 27AD0000 - Port 3 duration setting
        """
        duration_patterns = ['25AD', '26AD', '27AD']
        
        for port_num, pattern in enumerate(duration_patterns, 1):
            pattern_pos = hex_data.find(pattern)
            
            if pattern_pos >= 0 and pattern_pos + 8 <= len(hex_data):
                duration_hex = hex_data[pattern_pos:pattern_pos + 8]
                if duration_hex.startswith(pattern):
                    duration_value_hex = duration_hex[4:]
                    try:
                        duration_bytes = bytes.fromhex(duration_value_hex)
                        duration_value = int.from_bytes(duration_bytes, "little")
                        
                        self.zones[port_num]['duration_setting'] = duration_value
                        logger.debug("Port %d duration updated: %d", port_num, duration_value)
                    except ValueError as e:
                        logger.debug("Port %d duration conversion error: %s", port_num, e)
                        self.zones[port_num]['duration_setting'] = 0

    def set_device_status(self, api_obj: dict, msg_time: float = None) -> None:
        """
        Override to handle additional status fields specific to the timer.
        """
        attr_id = api_obj.get('id')
        value = api_obj.get('value') or api_obj.get('state')
        
        if not value: return

        if attr_id == 'connected':
            self.connection_state = int(value) == 1
        elif attr_id == 'state':
            self.device_state = value
        
        # Always allow base class to try parsing it (handles Dxx patterns)
        super().set_device_status(api_obj, msg_time=msg_time)

    def get_device_status_ids(self):
        """
        Return all status IDs this device listens to.
        """
        return [f"D{self.address:02d}", "connected", "state"]

    def is_connected(self):
        """
        Check if device is connected.
        """
        return self.connection_state is True

    def get_zone_status(self, zone_number):
        """
        Get status for a specific zone (1-3).
        """
        if zone_number in self.zones:
            return self.zones[zone_number]
        return None
    
    def get_zone_countdown_timer(self, zone_number):
        """
        Get countdown timer for a specific zone in seconds.
        """
        zone = self.get_zone_status(zone_number)
        return zone['countdown_timer'] if zone else 0

    def get_zone_countdown_end_time(self, zone_number):
        """
        Get the absolute end time for a zone as a timestamp.
        """
        zone = self.get_zone_status(zone_number)
        if zone and zone.get('active') and zone.get('countdown_end_time'):
            return zone['countdown_end_time']
        return None
    
    def get_zone_duration_setting(self, zone_number):
        """
        Get duration setting for a specific zone.
        """
        zone = self.get_zone_status(zone_number)
        return zone['duration_setting'] if zone else 0
    
    def is_zone_active(self, zone_number):
        """
        Check if a specific zone is currently active (on).
        """
        zone = self.get_zone_status(zone_number)
        return zone['active'] if zone else False
    
    def get_zone_status_text(self, zone_number):
        """
        Get human-readable status text for a specific zone.
        """
        zone = self.get_zone_status(zone_number)
        if not zone:
            return "Unknown"
        
        status_map = {
            'on': 'On',
            'off_recent': 'Off (Recent)',
            'off_idle': 'Off (Idle)'
        }
        return status_map.get(zone['status'], zone['status'])

    def control_zone(self, api, zone_number, mode, duration=0):
        """
        Control a specific zone on the device.
        
        :param api: HomgarApi instance
        :param zone_number: Zone number (1-3)
        :param mode: 0 = OFF, 1 = ON
        :param duration: Duration in seconds (0 for indefinite)
        :return: API response
        """
        if zone_number not in [1, 2, 3]:
            raise ValueError("Zone number must be 1, 2, or 3")
        
        if not self.hub_device_name or not self.hub_product_key:
            raise ValueError("Hub device name and product key are required for control operations")
        
        return api.control_device_work_mode(
            device_name=self.hub_device_name,
            product_key=self.hub_product_key,
            mid=str(self.mid),
            addr=self.address,
            port=zone_number,
            mode=mode,
            duration=duration
        )

    def turn_on_zone(self, api, zone_number, duration=0):
        """
        Turn on a specific zone.
        
        :param api: HomgarApi instance
        :param zone_number: Zone number (1-3)
        :param duration: Duration in seconds (0 for indefinite)
        :return: API response
        """
        return self.control_zone(api, zone_number, 1, duration)

    def turn_off_zone(self, api, zone_number):
        """
        Turn off a specific zone.
        
        :param api: HomgarApi instance
        :param zone_number: Zone number (1-3)
        :return: API response
        """
        return self.control_zone(api, zone_number, 0, 0)

    def __str__(self):
        s = super().__str__()
        if self.connection_state is not None:
            status = "connected" if self.connection_state else "disconnected"
            s += f" ({status})"
        
        # Add zone status information
        active_zones = [str(zone) for zone in [1, 2, 3] if self.is_zone_active(zone)]
        if active_zones:
            s += f" [Active zones: {', '.join(active_zones)}]"
        
        return s


class HWG0538WRF(HomgarHubDevice):
    MODEL_CODES = [256]
    FRIENDLY_DESC = "HWG0538WRF Water Timer Hub"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        pass


class HomgarWeatherHub(HomgarHubDevice):
    MODEL_CODES = [257]
    FRIENDLY_DESC = "HomGar Weather Hub (HG01)"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.hum_current = None
        self.press_pa_current = None

    def get_device_status_ids(self):
        return ["connected", "state"]

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        pass
    

class HomgarWeatherStation(HomgarSubDevice):
    MODEL_CODES = [85]
    FRIENDLY_DESC = "HomGar Weather Station"

    def get_device_status_ids(self):
        return ["connected", "state", "D01"]

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        logger.debug("RAW D01 FROM HUB = %s", s)

        try:
            temp_str, hum_str, press_str, *_ = s.split(',')

            t, *_ = _parse_stats_value(temp_str)
            self.temp_mk_current = _temp_to_mk(t) if t is not None else None

            h, *_ = _parse_stats_value(hum_str)
            self.hum_current = _safe_int(h)

            # Pression (ex: "P=10070(10080/10060/1)")
            if press_str.startswith("P="):
                press_str = press_str[2:]

            p, *_ = _parse_stats_value(press_str)
            self.press_pa_current = _safe_int(p)

        except Exception as e:
            logger.debug("Error parsing D01 payload '%s': %s", s, e)


class HomgarIndoorSensor(HomgarSubDevice):
    MODEL_CODES = [86]
    FRIENDLY_DESC = "HomGar Indoor Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.hum_current = None

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        temp_str, hum_str, *_ = s.split(',')

        t, *_ = _parse_stats_value(temp_str)
        self.temp_mk_current = _temp_to_mk(t) if t is not None else None

        h, *_ = _parse_stats_value(hum_str)
        self.hum_current = _safe_int(h)


MODEL_CODE_MAPPING = {
    code: clazz
    for clazz in (
        RainPointDisplayHub,
        RainPointSoilMoistureSensor,
        RainPointRainSensor,
        RainPointAirSensor,
        RainPoint2ZoneTimer,
        DiivooWT11W,
        HWG0538WRF,
        HomgarWeatherHub,
        HomgarWeatherStation,
        HomgarIndoorSensor,
        HTV405FRF
    ) for code in clazz.MODEL_CODES
}
