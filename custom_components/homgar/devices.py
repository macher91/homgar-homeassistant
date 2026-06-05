import re
import logging
from typing import List
from datetime import datetime, timezone
from .tlv import get_records_by_dp_id, t4date

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
        if not s: return

        if '#' in s:
            hex_data = s.split('#')[1]
            if len(hex_data) >= 8:
                self.hw_sequence = hex_data[2:8]

        records = get_records_by_dp_id(s)
        if not records:
            return

        if msg_time:
            self.last_sync_time = msg_time

        # Get current frame time
        current_time_s = None
        if 254 in records:  # 0xFE
            current_time_s = t4date(records[254]['value'])
        if not current_time_s:
            current_time_s = msg_time if msg_time else datetime.now().timestamp()

        for i in [1, 2, 3, 4]:
            wk_state_dp = 0x19 + (i - 1)
            event_time_dp = 0x21 + (i - 1)
            duration_dp = 0x25 + (i - 1)

            if wk_state_dp in records:
                val = records[wk_state_dp]['value']
                if val is not None:
                    self.zones[i]['active'] = bool(val & 1)
                    if val == 0:
                        self.zones[i]['status'] = 'off_recent'
                    elif val == 0x20:
                        self.zones[i]['status'] = 'off_idle'
                    else:
                        self.zones[i]['status'] = 'on'

            if duration_dp in records:
                val = records[duration_dp]['value']
                if val is not None:
                    self.zones[i]['duration_setting'] = val

            if event_time_dp in records:
                val = records[event_time_dp]['value']
                event_time_s = t4date(val)
                if event_time_s and event_time_s > current_time_s:
                    rem_s = round(event_time_s - current_time_s)
                    self.zones[i]['countdown_timer'] = rem_s
                else:
                    self.zones[i]['countdown_timer'] = 0
                    if self.zones[i]['active']:
                        logger.debug("Zone %d timer expired, forcing active=False", i)
                        self.zones[i]['active'] = False
                        self.zones[i]['status'] = 'off_idle'

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



class DiivooWTBase(HomgarSubDevice):
    """
    Base class for Diivoo WT-series Water Timers.
    """

    # --- Subclass configuration (override in subclasses) ---
    ZONE_NUMBERS: list = []

    def __init__(self, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.zones = {
            z: {"active": False, "status": "off_idle", "countdown_timer": 0,
                "countdown_end_time": None, "duration_setting": 0}
            for z in self.ZONE_NUMBERS
        }
        self.connection_state = None
        self.device_state = None
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    # --- Hex status parsing ---

    def _parse_device_specific_status_d_value(self, s, msg_time=None):
        """
        Parses the device-specific hex status (format: 11#[hex_data]).
        """
        logger.debug("--- PARSING DIIVOO HEX STATUS ---")

        self.raw_status = s

        if not s:
            return

        if '#' in s:
            hex_data = s.split('#')[1]
            self.hex_status_data = hex_data
            if len(hex_data) >= 8:
                self.sequence = hex_data[2:8]

        try:
            records = get_records_by_dp_id(s)
            if not records:
                return

            current_time_s = None
            if 254 in records:
                current_time_s = t4date(records[254]['value'])
            if not current_time_s:
                current_time_s = msg_time if msg_time else datetime.now().timestamp()

            for port_num in self.ZONE_NUMBERS:
                wk_state_dp = 0x19 + (port_num - 1)
                event_time_dp = 0x21 + (port_num - 1)
                duration_dp = 0x25 + (port_num - 1)

                if wk_state_dp in records:
                    val = records[wk_state_dp]['value']
                    if val is not None:
                        self.zones[port_num]['active'] = bool(val & 1)
                        if val == 0:
                            self.zones[port_num]['status'] = 'off_recent'
                        elif val == 0x20:
                            self.zones[port_num]['status'] = 'off_idle'
                        else:
                            self.zones[port_num]['status'] = 'on'
                        logger.debug("Zone %d status: %s", port_num, self.zones[port_num]['status'])

                if duration_dp in records:
                    val = records[duration_dp]['value']
                    if val is not None:
                        self.zones[port_num]['duration_setting'] = val
                        logger.debug("Zone %d duration: %d", port_num, val)

                if event_time_dp in records:
                    val = records[event_time_dp]['value']
                    event_time_s = t4date(val)
                    if event_time_s and event_time_s > current_time_s:
                        rem_s = round(event_time_s - current_time_s)
                        self.zones[port_num]['countdown_timer'] = rem_s

                        base_time = msg_time if msg_time else datetime.now().timestamp()
                        new_end_time = base_time + rem_s

                        old_val = self.zones[port_num].get('last_event_time_val')
                        if val != old_val:
                            self.zones[port_num]['countdown_end_time'] = new_end_time
                            self.zones[port_num]['last_event_time_val'] = val
                    else:
                        self.zones[port_num]['countdown_timer'] = 0
                        self.zones[port_num]['countdown_end_time'] = None
                        self.zones[port_num]['last_event_time_val'] = 0
                        if self.zones[port_num]['active']:
                            logger.debug("Zone %d timer expired, forcing active=False", port_num)
                            self.zones[port_num]['active'] = False
                            self.zones[port_num]['status'] = 'off_idle'

        except Exception as e:
            logger.error("Error parsing hex data: %s", e)
            self.parse_error = str(e)

    # --- Device status handling ---

    def set_device_status(self, api_obj: dict, msg_time: float = None) -> None:
        """Override to handle additional status fields specific to the timer."""
        attr_id = api_obj.get('id')
        value = api_obj.get('value') or api_obj.get('state')

        if not value: return

        if attr_id == 'connected':
            self.connection_state = int(value) == 1
        elif attr_id == 'state':
            self.device_state = value

        super().set_device_status(api_obj, msg_time=msg_time)

    def get_device_status_ids(self):
        """Return all status IDs this device listens to."""
        return [f"D{self.address:02d}", "connected", "state"]

    # --- Zone accessors ---

    def is_connected(self):
        """Check if device is connected."""
        return self.connection_state is True

    def get_zone_status(self, zone_number):
        """Get status dict for a specific zone."""
        return self.zones.get(zone_number)

    def get_zone_countdown_timer(self, zone_number):
        """Get countdown timer for a specific zone in seconds."""
        zone = self.get_zone_status(zone_number)
        return zone['countdown_timer'] if zone else 0

    def get_zone_countdown_end_time(self, zone_number):
        """Get the absolute end time for a zone as a timestamp."""
        zone = self.get_zone_status(zone_number)
        if zone and zone.get('active') and zone.get('countdown_end_time'):
            return zone['countdown_end_time']
        return None

    def get_zone_duration_setting(self, zone_number):
        """Get duration setting for a specific zone."""
        zone = self.get_zone_status(zone_number)
        return zone['duration_setting'] if zone else 0

    def is_zone_active(self, zone_number):
        """Check if a specific zone is currently active (on)."""
        zone = self.get_zone_status(zone_number)
        return zone['active'] if zone else False

    def get_zone_status_text(self, zone_number):
        """Get human-readable status text for a specific zone."""
        zone = self.get_zone_status(zone_number)
        if not zone:
            return "Unknown"
        status_map = {
            'on': 'On',
            'off_recent': 'Off (Recent)',
            'off_idle': 'Off (Idle)'
        }
        return status_map.get(zone['status'], zone['status'])

    # --- Zone control ---

    def control_zone(self, api, zone_number, mode, duration=0):
        """
        Control a specific zone on the device.

        :param api: HomgarApi instance
        :param zone_number: Zone number
        :param mode: 0 = OFF, 1 = ON
        :param duration: Duration in seconds (0 for indefinite)
        :return: API response
        """
        if zone_number not in self.ZONE_NUMBERS:
            raise ValueError(f"Zone number must be one of {self.ZONE_NUMBERS}")

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
        """Turn on a specific zone."""
        return self.control_zone(api, zone_number, 1, duration)

    def turn_off_zone(self, api, zone_number):
        """Turn off a specific zone."""
        return self.control_zone(api, zone_number, 0, 0)

    def __str__(self):
        s = super().__str__()
        if self.connection_state is not None:
            status = "connected" if self.connection_state else "disconnected"
            s += f" ({status})"

        active_zones = [str(z) for z in self.ZONE_NUMBERS if self.is_zone_active(z)]
        if active_zones:
            s += f" [Active zones: {', '.join(active_zones)}]"

        return s


class DiivooWT11W(DiivooWTBase):
    """Diivoo WT-11W 3-Zone Water Timer (modelCode 271)."""
    MODEL_CODES = [271]
    FRIENDLY_DESC = "Diivoo WT-11W 3-Zone Water Timer"

    ZONE_NUMBERS = [1, 2, 3]


class DiivooWT13W(DiivooWTBase):
    """Diivoo WT-13W 4-Zone Water Timer (modelCode 272)."""
    MODEL_CODES = [272]
    FRIENDLY_DESC = "Diivoo WT-13W 4-Zone Water Timer"

    ZONE_NUMBERS = [1, 2, 3, 4]


class DiivooWT09W(DiivooWTBase):
    """Diivoo WT-09W 2-Zone Water Timer (HTV0537FRF, modelCode 270)."""
    MODEL_CODES = [270]
    FRIENDLY_DESC = "Diivoo WT-09W 2-Zone Water Timer"

    ZONE_NUMBERS = [1, 2]


class DiivooWT07W(DiivooWTBase):
    """Diivoo WT-07W 1-Zone Water Timer (HTV0535FR, modelCode 269)."""
    MODEL_CODES = [269]
    FRIENDLY_DESC = "Diivoo WT-07W 1-Zone Water Timer"

    ZONE_NUMBERS = [1]


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
        DiivooWT13W,
        DiivooWT11W,
        DiivooWT09W,
        DiivooWT07W,
        HWG0538WRF,
        HomgarWeatherHub,
        HomgarWeatherStation,
        HomgarIndoorSensor,
        HTV405FRF
    ) for code in clazz.MODEL_CODES
}
