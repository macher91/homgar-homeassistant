import re
import logging
from typing import List

logger = logging.getLogger(__name__)

STATS_VALUE_REGEX = re.compile(r'^(\d+)\((\d+)/(\d+)/(\d+)\)')


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

    def set_device_status(self, api_obj: dict) -> None:
        """
        Called after a call to /app/device/getDeviceStatus with an entry from $.data.subDeviceStatus
        that matches one of the IDs returned by get_device_status_ids().
        Should update the device status with the contents of the given API response.
        :param api_obj: The $.data.subDeviceStatus API response that should be used to update this device's status
        """
        if api_obj['id'] == f"D{self.address:02d}":
            self._parse_status_d_value(api_obj['value'])

    def _parse_status_d_value(self, val: str) -> None:
        """
        Parses a $.data.subDeviceStatus[x].value field for an entry with ID 'Dxx' where xx is the device address.
        These fields consist of a common part and a device-specific part separated by a ';'.
        This call should update the device status.
        :param val: Value of the $.data.subDeviceStatus[x].value field to apply
        """
        general_str, specific_str = val.split(';')
        self._parse_general_status_d_value(general_str)
        self._parse_device_specific_status_d_value(specific_str)

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

    def _parse_device_specific_status_d_value(self, s: str):
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
    def __init__(self, subdevices, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices = subdevices
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    def __str__(self):
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"

    def _parse_device_specific_status_d_value(self, s):
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

    def _parse_device_specific_status_d_value(self, s):
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

    def set_device_status(self, api_obj):
        dev_id = api_obj['id']
        val = api_obj['value']
        if dev_id == "state":
            self.battery_state, self.wifi_rssi = [int(s) for s in val.split(',')]
        elif dev_id == "connected":
            self.connected = int(val) == 1
        else:
            super().set_device_status(api_obj)

    def _parse_device_specific_status_d_value(self, s):
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
    MODEL_CODES = [72]
    FRIENDLY_DESC = "Soil Moisture Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.moist_percent_current = None
        self.light_lux_current = None

    def _parse_device_specific_status_d_value(self, s):
        """
        Observed example value:
        766,52,G=31351

        Deduced meaning:
        temp[.1F],soil-moisture[%],G=light[.1lux]
        """
        temp_str, moist_str, light_str = s.split(',')
        self.temp_mk_current = _temp_to_mk(temp_str)
        self.moist_percent_current = int(moist_str)
        self.light_lux_current = int(light_str[2:]) * .1

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3-273.15:.1f}°C / {self.moist_percent_current}% / {self.light_lux_current:.1f}lx"
        return s


class RainPointRainSensor(HomgarSubDevice):
    MODEL_CODES = [87]
    FRIENDLY_DESC = "High Precision Rain Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rainfall_mm_total = None
        self.rainfall_mm_hour = None
        self.rainfall_mm_daily = None
        self.rainfall_mm_total = None

    def _parse_device_specific_status_d_value(self, s):
        """
        Observed example value:
        R=270(0/0/270)

        Deduced meaning:
        R=total?[.1mm](hour?[.1mm]/24hours?[.1mm]/7days?[.1mm])
        """
        self.rainfall_mm_total, self.rainfall_mm_hour, self.rainfall_mm_daily, self.rainfall_mm_7days = [.1*v for v in _parse_stats_value(s[2:])]

    def __str__(self):
        s = super().__str__()
        if self.rainfall_mm_total:
            s += f": {self.rainfall_mm_total}mm total / {self.rainfall_mm_hour}mm 1h / {self.rainfall_mm_daily}mm 24h / {self.rainfall_mm_7days}mm 7days"
        return s


class RainPointAirSensor(HomgarSubDevice):
    MODEL_CODES = [262]
    FRIENDLY_DESC = "Outdoor Air Humidity Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.temp_mk_daily_max = None
        self.temp_mk_daily_min = None
        self.temp_trend = None
        self.hum_current = None
        self.hum_daily_max = None
        self.hum_daily_min = None
        self.hum_trend = None

    def _parse_device_specific_status_d_value(self, s):
        """
        Observed example value:
        755(1020/588/1),54(91/24/1),

        Deduced meaning:
        temp[.1F](day-max/day-min/trend?),humidity[%](day-max/day-min/trend?)
        """
        temp_str, hum_str, *_ = s.split(',')
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

    def _parse_device_specific_status_d_value(self, s):
        """
        TODO deduce meaning of these fields.
        Observed example value:
        0,9,0,0,0,0|0,1291,0,0,0,0

        What we know so far:
        left/right zone separated by '|' character
        fields for each zone: ?,last-usage[.1l],?,?,?,?
        """
        pass


class DiivooWT11W(HomgarSubDevice):
    MODEL_CODES = [271]
    FRIENDLY_DESC = "Diivoo WT-11W 3-Zone Water Timer"

    def __init__(self, hub_device_name=None, hub_product_key=None, **kwargs):
        super().__init__(**kwargs)
        self.zones = {
            1: {"active": False, "status": "off_idle", "countdown_timer": 0, "duration_setting": 0},
            2: {"active": False, "status": "off_idle", "countdown_timer": 0, "duration_setting": 0},
            3: {"active": False, "status": "off_idle", "countdown_timer": 0, "duration_setting": 0}
        }
        self.connection_state = None
        self.device_state = None
        self.hub_device_name = hub_device_name
        self.hub_product_key = hub_product_key

    def _parse_device_specific_status_d_value(self, s):
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
        logger.info("=== PARSING DIIVOO HEX STATUS ===")
        logger.info("Raw status string: %s", s)
        
        self.raw_status = s
        
        if '#' not in s:
            logger.warning("No '#' found in status string - expected format: 11#[hex_data]")
            return
            
        parts = s.split('#')
        if len(parts) < 2:
            logger.warning("Invalid format - expected format: 11#[hex_data], got: %s", s)
            return
            
        prefix = parts[0]
        hex_data = parts[1]
        
        logger.info("Status prefix: %s", prefix)
        logger.info("Hex data: %s", hex_data)
        logger.info("Hex data length: %d characters", len(hex_data))
        
        self.hex_status_data = hex_data
        
        # Parse the hex data according to the documented format
        try:
            logger.info("Starting hex data parsing...")
            self._parse_hex_status_data(hex_data)
            logger.info("Hex data parsing completed successfully")
        except Exception as e:
            logger.error("Error parsing hex data: %s", e)
            # If parsing fails, store raw data for debugging
            self.parse_error = str(e)
            
        logger.info("=== END PARSING DIIVOO HEX STATUS ===")
    
    def _parse_hex_status_data(self, hex_data):
        """
        Parse the hex-encoded status data into structured information.
        Based on the documented format:
        - 17 E19F00 - sequence (index 0-6)
        - 19 D821 - port 1 status (index 6-10) 
        - 1A D800 - port 2 status (index 10-14)
        - 1B D800 - port 3 status (index 14-18)
        - ... timers and duration settings follow
        """
        if len(hex_data) < 50:  # Minimum length for basic parsing
            return
            
        # Parse sequence (first 6 characters after the initial bytes)
        if len(hex_data) >= 8:
            self.sequence = hex_data[2:8]
        
        # Parse port statuses by looking for the specific byte patterns
        self._parse_port_statuses_precise(hex_data)
        self._parse_countdown_timers_precise(hex_data)
        self._parse_duration_settings_precise(hex_data)
    
    def _parse_port_statuses_precise(self, hex_data):
        """
        Parse port statuses using the documented byte positions.
        Looking for patterns like:
        - 19D821 - port 1 status (on)
        - 1AD820 - port 2 status (off_recent)
        - 1BD800 - port 3 status (off_idle)
        """
        logger.info("--- Parsing Port Statuses ---")
        
        status_map = {
            'D821': 'on',
            'D820': 'off_recent',
            'D800': 'off_idle'
        }
        
        # Look for port status patterns in the hex data
        port_patterns = ['19D8', '1AD8', '1BD8']  # Port 1, 2, 3 patterns
        
        for port_num, pattern in enumerate(port_patterns, 1):
            logger.info("Searching for Port %d pattern: %s", port_num, pattern)
            
            # Find the pattern in the hex data
            pattern_pos = hex_data.find(pattern)
            logger.info("Pattern %s found at position: %d", pattern, pattern_pos)
            
            if pattern_pos >= 0 and pattern_pos + 6 <= len(hex_data):
                # Extract the full 6-character pattern (e.g., '19D821')
                full_pattern = hex_data[pattern_pos:pattern_pos + 6]
                # Extract just the status code (last 4 characters)
                status_hex = full_pattern[2:]  # Get 'D821', 'D820', etc.
                
                logger.info("Port %d full pattern: %s", port_num, full_pattern)
                logger.info("Port %d status hex: %s", port_num, status_hex)
                
                if status_hex in status_map:
                    old_active = self.zones[port_num]['active']
                    old_status = self.zones[port_num]['status']
                    
                    self.zones[port_num]['active'] = status_map[status_hex] == 'on'
                    self.zones[port_num]['status'] = status_map[status_hex]
                    
                    logger.info("Port %d status updated:", port_num)
                    logger.info("  Active: %s → %s", old_active, self.zones[port_num]['active'])
                    logger.info("  Status: %s → %s", old_status, self.zones[port_num]['status'])
                else:
                    logger.warning("Port %d unknown status hex: %s", port_num, status_hex)
            else:
                logger.warning("Port %d pattern not found or incomplete", port_num)
    
    def _parse_countdown_timers_precise(self, hex_data):
        """
        Parse countdown timers for each port.
        Looking for patterns like:
        - 21B79AE7DE15 - Port 1 countdown timer
        - 22B700000000 - Port 2 countdown timer
        - 23B700000000 - Port 3 countdown timer
        """
        logger.info("--- Parsing Countdown Timers ---")
        
        timer_patterns = ['21B7', '22B7', '23B7']  # Port 1, 2, 3 timer patterns
        
        for port_num, pattern in enumerate(timer_patterns, 1):
            logger.info("Searching for Port %d timer pattern: %s", port_num, pattern)
            
            # Find the pattern in the hex data
            pattern_pos = hex_data.find(pattern)
            logger.info("Timer pattern %s found at position: %d", pattern, pattern_pos)
            
            if pattern_pos >= 0 and pattern_pos + 12 <= len(hex_data):
                # Extract the full timer data (pattern + 8 hex chars)
                timer_hex = hex_data[pattern_pos:pattern_pos + 12]
                
                logger.info("Port %d timer hex: %s", port_num, timer_hex)
                
                if timer_hex.startswith(pattern):
                    # Extract the 8-digit timer value (skip the 4-char pattern)
                    timer_value_hex = timer_hex[4:]  # Skip '21B7', '22B7', etc.
                    logger.info("Port %d timer value hex: %s", port_num, timer_value_hex)
                    
                    try:
                        # Convert hex to integer (timer value)
                        timer_value = int(timer_value_hex, 16)
                        old_timer = self.zones[port_num]['countdown_timer']
                        self.zones[port_num]['countdown_timer'] = timer_value
                        
                        logger.info("Port %d timer updated: %d → %d seconds", port_num, old_timer, timer_value)
                    except ValueError as e:
                        logger.error("Port %d timer conversion error: %s", port_num, e)
                        self.zones[port_num]['countdown_timer'] = 0
                else:
                    logger.warning("Port %d timer hex doesn't start with expected pattern", port_num)
            else:
                logger.warning("Port %d timer pattern not found or incomplete", port_num)
    
    def _parse_duration_settings_precise(self, hex_data):
        """
        Parse duration settings for each port.
        Looking for patterns like:
        - 25ADDC05 - Port 1 duration setting
        - 26AD0000 - Port 2 duration setting
        - 27AD0000 - Port 3 duration setting
        """
        logger.info("--- Parsing Duration Settings ---")
        
        duration_patterns = ['25AD', '26AD', '27AD']  # Port 1, 2, 3 duration patterns
        
        for port_num, pattern in enumerate(duration_patterns, 1):
            logger.info("Searching for Port %d duration pattern: %s", port_num, pattern)
            
            # Find the pattern in the hex data
            pattern_pos = hex_data.find(pattern)
            logger.info("Duration pattern %s found at position: %d", pattern, pattern_pos)
            
            if pattern_pos >= 0 and pattern_pos + 8 <= len(hex_data):
                # Extract the full duration data (pattern + 4 hex chars)
                duration_hex = hex_data[pattern_pos:pattern_pos + 8]
                
                logger.info("Port %d duration hex: %s", port_num, duration_hex)
                
                if duration_hex.startswith(pattern):
                    # Extract the 4-digit duration value (skip the 4-char pattern)
                    duration_value_hex = duration_hex[4:]  # Skip '25AD', '26AD', etc.
                    logger.info("Port %d duration value hex: %s", port_num, duration_value_hex)
                    
                    try:
                        # Convert hex to integer (duration setting)
                        duration_value = int(duration_value_hex, 16)
                        old_duration = self.zones[port_num]['duration_setting']
                        self.zones[port_num]['duration_setting'] = duration_value
                        
                        logger.info("Port %d duration updated: %d → %d", port_num, old_duration, duration_value)
                    except ValueError as e:
                        logger.error("Port %d duration conversion error: %s", port_num, e)
                        self.zones[port_num]['duration_setting'] = 0
                else:
                    logger.warning("Port %d duration hex doesn't start with expected pattern", port_num)
            else:
                logger.warning("Port %d duration pattern not found or incomplete", port_num)

    def set_device_status(self, api_obj: dict) -> None:
        """
        Override to handle additional status fields specific to the timer.
        """
        logger.info("=== DIIVOO DEVICE STATUS UPDATE ===")
        logger.info("DiivooWT11W.set_device_status called with: %s", api_obj)
        
        dev_id = api_obj['id']
        val = api_obj['value']
        
        logger.info("Device ID: %s", dev_id)
        logger.info("Value: %s", val)
        logger.info("Expected device address: D%02d", self.address)
        
        if dev_id == 'connected':
            old_state = self.connection_state
            self.connection_state = int(val) == 1
            logger.info("Connection state updated: %s → %s", old_state, self.connection_state)
            
        elif dev_id == 'state':
            # State format appears to be "0,-15" - store raw for now
            old_state = self.device_state
            self.device_state = val
            logger.info("Device state updated: %s → %s", old_state, self.device_state)
            
        elif dev_id == f"D{self.address:02d}":
            logger.info("Processing device-specific status for address %d", self.address)
            logger.info("Raw hex status value: %s", val)
            
            # Store zones before parsing
            zones_before = {}
            for zone_num in [1, 2, 3]:
                zones_before[zone_num] = dict(self.zones[zone_num])
            
            # Handle device-specific status parsing
            self._parse_device_specific_status_d_value(val)
            
            # Log changes
            logger.info("Zone status changes:")
            for zone_num in [1, 2, 3]:
                before = zones_before[zone_num]
                after = self.zones[zone_num]
                if before != after:
                    logger.info("  Zone %d: %s → %s", zone_num, before, after)
                    for key in ['active', 'status', 'countdown_timer', 'duration_setting']:
                        if before.get(key) != after.get(key):
                            logger.info("    %s: %s → %s", key, before.get(key), after.get(key))
                else:
                    logger.info("  Zone %d: No changes", zone_num)
        else:
            logger.info("Unhandled device ID: %s", dev_id)
            # Handle RF RSSI and other general status if needed
            if hasattr(self, 'rf_rssi'):
                # This is a simplified approach - in a real implementation,
                # you might need to parse the general status format
                pass
                
        logger.info("=== END DIIVOO DEVICE STATUS UPDATE ===")

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

    def _parse_device_specific_status_d_value(self, s):
        """
        Parses the device-specific status for HWG0538WRF hub device.
        Hub devices typically don't parse device-specific status.
        """
        pass



MODEL_CODE_MAPPING = {
    code: clazz
    for clazz in (
        RainPointDisplayHub,
        RainPointSoilMoistureSensor,
        RainPointRainSensor,
        RainPointAirSensor,
        RainPoint2ZoneTimer,
        DiivooWT11W,
        HWG0538WRF
    ) for code in clazz.MODEL_CODES
}
