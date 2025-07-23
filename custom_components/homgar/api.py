import binascii
import hashlib
import os
import json
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Callable

import requests
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from .devices import HomgarHome, MODEL_CODE_MAPPING, HomgarHubDevice
from .logutil import TRACE, get_logger

logger = get_logger(__file__)


class HomgarApiException(Exception):
    def __init__(self, code, msg):
        super().__init__()
        self.code = code
        self.msg = msg

    def __str__(self):
        s = f"HomGar API returned code {self.code}"
        if self.msg:
            s += f" ('{self.msg}')"
        return s


class HomgarApi:
    def __init__(
            self,
            auth_cache: Optional[dict] = None,
            api_base_url: str = "https://region3.homgarus.com",
            requests_session: requests.Session = None
    ):
        """
        Create an object for interacting with the Homgar API
        :param auth_cache: A dictionary in which authentication information will be stored.
            Save this dict on exit and supply it again next time constructing this object to avoid logging in
            if a valid token is still present.
        :param api_base_url: The base URL for the Homgar API. Omit trailing slash.
        :param requests_session: Optional requests lib session to use. New session is created if omitted.
        """
        self.session = requests_session or requests.Session()
        self.cache = auth_cache or {}
        self.base = api_base_url
        self.mqtt_client = None
        self.mqtt_connected = False
        self.status_callbacks = []
        self.subscription_data = None
        self._mqtt_lock = threading.Lock()
        self._subscription_devices = []
        self._subscription_hids = []

    def _request(self, method, url, with_auth=True, headers=None, **kwargs):
        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        headers = {"lang": "en", "appCode": "1", **(headers or {})}
        if with_auth:
            headers["auth"] = self.cache["token"]
        response = self.session.request(method, url, headers=headers, **kwargs)
        logger.log(TRACE, "-[%03d]-> %s", response.status_code, response.text)
        return response

    def _request_json(self, method, path, **kwargs):
        response = self._request(method, self.base + path, **kwargs).json()
        code = response.get('code')
        if code != 0:
            raise HomgarApiException(code, response.get('msg'))
        return response.get('data')

    def _get_json(self, path, **kwargs):
        return self._request_json("GET", path, **kwargs)

    def _get_push_product_key(self) -> str:
        """Get product key for push notifications. This should be obtained from API or device configuration."""
        # In a real implementation, this would be fetched from the API response or device configuration
        # This is a placeholder - the actual key should come from the server response
        # or be configurable through the integration setup
        return "push_product_key_placeholder"
    
    def _post_json(self, path, body, **kwargs):
        return self._request_json("POST", path, json=body, **kwargs)

    def login(self, email: str, password: str, area_code="31") -> None:
        """
        Perform a new login.
        :param email: Account e-mail
        :param password: Account password
        :param area_code: Seems to need to be the phone country code associated with the account, e.g. "31" for NL
        """
        data = self._post_json("/auth/basic/app/login", {
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode('utf-8')
        }, with_auth=False)
        self.cache['email'] = email
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.utcnow().timestamp() + data.get('tokenExpired')
        self.cache['refresh_token'] = data.get('refreshToken')

    def get_homes(self) -> List[HomgarHome]:
        """
        Retrieves all HomgarHome objects associated with the logged in account.
        Requires first logging in.
        :return: List of HomgarHome objects
        """
        data = self._get_json("/app/member/appHome/list")
        return [HomgarHome(hid=h.get('hid'), name=h.get('homeName')) for h in data]

    def get_devices_for_hid(self, hid: str) -> List[HomgarHubDevice]:
        """
        Retrieves a device tree associated with the home identified by the given hid (home ID).
        This function returns a list of hubs associated with the home. Each hub contains associated
        subdevices that use the hub as gateway.
        :param hid: The home ID to retrieve hubs and associated subdevices for
        :return: List of hubs with associated subdevicse
        """
        data = self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})
        hubs = []

        def device_base_props(dev_data):
            return dict(
                model=dev_data.get('model'),
                model_code=dev_data.get('modelCode'),
                name=dev_data.get('name'),
                did=dev_data.get('did'),
                mid=dev_data.get('mid'),
                address=dev_data.get('addr'),
                port_number=dev_data.get('portNumber'),
                alerts=dev_data.get('alerts'),
            )

        def get_device_class(dev_data):
            model_code = dev_data.get('modelCode')
            if model_code not in MODEL_CODE_MAPPING:
                logger.warning("Unknown device '%s' with modelCode %d", dev_data.get('model'), model_code)
                return None
            return MODEL_CODE_MAPPING[model_code]

        for hub_data in data:
            subdevices = []
            for subdevice_data in hub_data.get('subDevices', []):
                did = subdevice_data.get('did')
                if did == 1:
                    # Display hub
                    continue
                subdevice_class = get_device_class(subdevice_data)
                if subdevice_class is None:
                    continue
                
                # Create subdevice with additional hub information for control
                subdevice_props = device_base_props(subdevice_data)
                subdevice_props['hub_device_name'] = hub_data.get('deviceName')
                subdevice_props['hub_product_key'] = hub_data.get('productKey')
                
                subdevices.append(subdevice_class(**subdevice_props))

            hub_class = get_device_class(hub_data)
            if hub_class is None:
                hub_class = HomgarHubDevice

            # Create hub device with additional attributes for MQTT subscription
            hub_props = device_base_props(hub_data)
            hub_props['hub_device_name'] = hub_data.get('deviceName')
            hub_props['hub_product_key'] = hub_data.get('productKey')
            
            hubs.append(hub_class(
                **hub_props,
                subdevices=subdevices
            ))

        return hubs

    def get_device_status(self, hub: HomgarHubDevice) -> None:
        """
        Updates the device status of all subdevices associated with the given hub device.
        :param hub: The hub to update
        """
        data = self._get_json("/app/device/getDeviceStatus", params={"mid": str(hub.mid)})
        id_map = {status_id: device for device in [hub, *hub.subdevices] for status_id in device.get_device_status_ids()}

        for subdevice_status in data['subDeviceStatus']:
            device = id_map.get(subdevice_status['id'])
            if device is not None:
                device.set_device_status(subdevice_status)

    def control_device_work_mode(self, device_name: str, product_key: str, mid: str, addr: int, port: int, mode: int, duration: int = 0) -> dict:
        """
        Controls the work mode of a device (e.g., irrigation timer).
        
        :param device_name: Device name (e.g., "MAC-XXXXXXXXXXXX")
        :param product_key: Product key
        :param mid: Device MID
        :param addr: Device address
        :param port: Port/zone number (1-3 for DiivooWT11W)
        :param mode: 0 = OFF, 1 = ON
        :param duration: Duration in seconds (0 for indefinite)
        :return: API response data
        """
        return self._post_json("/app/device/controlWorkMode", {
            "deviceName": device_name,
            "productKey": product_key,
            "mid": str(mid),
            "addr": addr,
            "port": port,
            "mode": mode,
            "duration": duration,
            "param": ""
        })

    def ensure_logged_in(self, email: str, password: str, area_code: str = "31") -> None:
        """
        Ensures this API object has valid credentials.
        Attempts to verify the token stored in the auth cache. If invalid, attempts to login.
        See login() for parameter info.
        """
        if (
                self.cache.get('email') != email or
                datetime.fromtimestamp(self.cache.get('token_expires', 0)) - datetime.utcnow() < timedelta(minutes=60)
        ):
            self.login(email, password, area_code=area_code)

    def subscribe_to_device_status(self, hid: str, hid_list: List[str], devices: List[dict]) -> Optional[dict]:
        """
        Subscribe to real-time device status updates via MQTT.
        
        :param hid: Primary home ID
        :param hid_list: List of all home IDs
        :param devices: List of device dictionaries with deviceName, mid, productKey
        :return: MQTT connection details or None if failed
        """
        logger.info("Starting device status subscription for HID: %s, devices: %d", hid, len(devices))
        if mqtt is None:
            logger.error("MQTT not available, install paho-mqtt package")
            return None
            
        device_id = str(uuid.uuid4()).replace('-', '')[:20]
        logger.debug("Generated device ID for subscription: %s", device_id)
        
        subscribe_data = {
            "hid": hid,
            "hidList": hid_list,
            "subscribe": devices,
            "unsubscribe": [],
            "userInfo": {
                "deviceName": device_id,
                "deviceType": 1,
                "notice": 0,
                "productKey": self._get_push_product_key(),
                "pushId": str(uuid.uuid4()).replace('-', '')
            }
        }
        
        try:
            logger.debug("Sending subscription request to API")
            response = self._post_json("/app/device/subscribeStatus", subscribe_data)
            logger.debug("Subscription API response: %s", response)
            self.subscription_data = response
            # Store subscription parameters for renewal
            self._subscription_devices = devices
            self._subscription_hids = hid_list
            mqtt_host = response.get('mqttHostUrl')
            if mqtt_host:
                logger.info("MQTT subscription successful, broker: %s", mqtt_host)
            else:
                logger.warning("MQTT subscription response missing mqttHostUrl")
            return response
        except Exception as e:
            logger.error("Failed to subscribe to device status: %s", e)
            return None

    def connect_mqtt(self, callback: Optional[Callable] = None) -> bool:
        """
        Connect to MQTT broker using subscription data.
        
        :param callback: Optional callback function for status updates
        :return: True if connection successful
        """
        logger.info("Starting MQTT connection")
        if not self.subscription_data:
            logger.error("No subscription data available for MQTT connection")
            return False
            
        if mqtt is None:
            logger.error("MQTT library not available")
            return False
            
        logger.debug("Subscription data available: %s", list(self.subscription_data.keys()) if self.subscription_data else None)
        logger.debug("Required fields in subscription data: mqttHostUrl=%s, deviceName=%s, productKey=%s, deviceSecret=%s", 
                    self.subscription_data.get('mqttHostUrl'), 
                    self.subscription_data.get('deviceName'),
                    self.subscription_data.get('productKey'),
                    "***" if self.subscription_data.get('deviceSecret') else None)
            
        if callback:
            self.status_callbacks.append(callback)
            logger.debug("Added status callback (total callbacks: %d)", len(self.status_callbacks))
            
        with self._mqtt_lock:
            if self.mqtt_client and self.mqtt_connected:
                logger.debug("MQTT already connected")
                return True
                
            try:
                logger.debug("Creating MQTT client")
                self.mqtt_client = mqtt.Client()
                self.mqtt_client.on_connect = self._on_mqtt_connect
                self.mqtt_client.on_message = self._on_mqtt_message
                self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
                
                # Set credentials
                device_name = self.subscription_data.get('deviceName')
                product_key = self.subscription_data.get('productKey')
                device_secret = self.subscription_data.get('deviceSecret')
                
                logger.debug("MQTT credentials - deviceName: %s, productKey: %s, deviceSecret: %s", 
                           device_name, product_key, "***" if device_secret else None)
                
                if device_name and product_key and device_secret:
                    username = f"{device_name}&{product_key}"
                    password = device_secret
                    logger.debug("Setting MQTT credentials with username: %s", username)
                    self.mqtt_client.username_pw_set(username, password)
                    logger.debug("MQTT credentials set successfully")
                else:
                    logger.error("Missing MQTT credentials: deviceName=%s, productKey=%s, deviceSecret=%s", 
                               device_name, product_key, "***" if device_secret else None)
                
                # Connect to broker
                mqtt_url = self.subscription_data.get('mqttHostUrl', '')
                logger.debug("MQTT broker URL from subscription: %s", mqtt_url)
                
                if ':' in mqtt_url:
                    host, port = mqtt_url.split(':')
                    port = int(port)
                else:
                    host = mqtt_url
                    port = 1883
                    
                logger.info("Attempting to connect to MQTT broker at %s:%d", host, port)
                
                try:
                    self.mqtt_client.connect(host, port, 60)
                    logger.debug("MQTT connect() call succeeded, starting loop")
                    self.mqtt_client.loop_start()
                    logger.debug("MQTT loop started successfully")
                    return True
                except Exception as connect_error:
                    logger.error("MQTT connection failed: %s", connect_error)
                    return False
                
            except Exception as e:
                logger.error("Failed to connect to MQTT: %s", e)
                return False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        logger.info("MQTT connection callback triggered with code: %s", rc)
        
        if rc == 0:
            logger.info("MQTT connected successfully")
            self.mqtt_connected = True
            
            # Subscribe to device status topics
            product_key = self.subscription_data.get('productKey')
            device_name = self.subscription_data.get('deviceName')
            
            logger.debug("Preparing to subscribe with productKey: %s, deviceName: %s", product_key, device_name)
            
            if product_key and device_name:
                topic = f"/{product_key}/{device_name}/user/status"
                logger.debug("Subscribing to MQTT topic: %s", topic)
                result = client.subscribe(topic)
                logger.info("MQTT subscription result: %s for topic: %s", result, topic)
            else:
                logger.error("Cannot subscribe to MQTT topic: missing productKey or deviceName")
        else:
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorised"
            }
            error_msg = error_messages.get(rc, f"Unknown error code {rc}")
            logger.error("MQTT connection failed with code %s: %s", rc, error_msg)
            self.mqtt_connected = False

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        logger.debug("MQTT message callback triggered")
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.info("=== MQTT MESSAGE RECEIVED ===")
            logger.info("Topic: %s", topic)
            logger.info("Raw payload: %s", payload)
            logger.info("Payload length: %d bytes", len(payload))
            logger.info("Payload hex: %s", payload.encode('utf-8').hex())
            
            # Try to parse as JSON
            try:
                data = json.loads(payload)
                logger.info("Successfully parsed as JSON:")
                logger.info("JSON structure: %s", json.dumps(data, indent=2))
                
                # Log detailed analysis of the JSON structure
                self._analyze_mqtt_json_message(data)
                
                # Call status callbacks
                logger.debug("Calling %d status callbacks with parsed data", len(self.status_callbacks))
                for i, callback in enumerate(self.status_callbacks):
                    try:
                        logger.debug("Executing callback %d", i)
                        callback(data)
                        logger.debug("Callback %d executed successfully", i)
                    except Exception as callback_error:
                        logger.error("Error in callback %d: %s", i, callback_error)
                        
            except json.JSONDecodeError as json_error:
                logger.warning("Failed to parse as JSON: %s", json_error)
                logger.info("Attempting alternative parsing methods...")
                
                # Try to parse as other formats
                self._analyze_non_json_mqtt_message(payload)
                
            logger.info("=== END MQTT MESSAGE ===")
                
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e)
    
    def _analyze_mqtt_json_message(self, data):
        """Analyze and log detailed information about JSON MQTT messages"""
        logger.info("MQTT JSON Analysis:")
        
        # Check for common fields
        if isinstance(data, dict):
            logger.info("Message type: Dictionary with %d keys", len(data))
            for key, value in data.items():
                logger.info("  Key '%s': %s (type: %s)", key, str(value)[:100], type(value).__name__)
                
                # Special handling for known fields
                if key == 'deviceId' or key == 'mid':
                    logger.info("    → Device identifier found: %s", value)
                elif key == 'status' or key == 'state':
                    logger.info("    → Device status/state found: %s", value)
                elif key == 'timestamp':
                    logger.info("    → Timestamp found: %s", value)
                elif key == 'data' and isinstance(value, dict):
                    logger.info("    → Nested data object with keys: %s", list(value.keys()))
                    
        elif isinstance(data, list):
            logger.info("Message type: List with %d items", len(data))
            for i, item in enumerate(data[:5]):  # Log first 5 items
                logger.info("  Item %d: %s (type: %s)", i, str(item)[:100], type(item).__name__)
        else:
            logger.info("Message type: %s, value: %s", type(data).__name__, str(data)[:200])
    
    def _analyze_non_json_mqtt_message(self, payload):
        """Analyze non-JSON MQTT messages"""
        logger.info("Non-JSON MQTT Analysis:")
        logger.info("Raw string: %s", payload)
        
        # Check for common patterns
        if payload.startswith('11#'):
            logger.info("  → Appears to be hex-encoded device status (starts with '11#')")
            hex_part = payload[3:]  # Remove '11#' prefix
            logger.info("  → Hex data: %s", hex_part)
            logger.info("  → Hex length: %d characters", len(hex_part))
            
            # Try to parse hex patterns
            self._analyze_hex_device_status(hex_part)
            
        elif ',' in payload:
            logger.info("  → Contains commas, might be CSV format")
            parts = payload.split(',')
            logger.info("  → %d parts: %s", len(parts), parts)
            
        elif ';' in payload:
            logger.info("  → Contains semicolons, might be semicolon-separated format")
            parts = payload.split(';')
            logger.info("  → %d parts: %s", len(parts), parts)
            
        elif '|' in payload:
            logger.info("  → Contains pipes, might be pipe-separated format")
            parts = payload.split('|')
            logger.info("  → %d parts: %s", len(parts), parts)
            
        else:
            logger.info("  → Unknown format, analyzing character patterns")
            logger.info("  → Contains digits: %s", any(c.isdigit() for c in payload))
            logger.info("  → Contains alpha: %s", any(c.isalpha() for c in payload))
            logger.info("  → Contains uppercase: %s", any(c.isupper() for c in payload))
            logger.info("  → Contains lowercase: %s", any(c.islower() for c in payload))
    
    def _analyze_hex_device_status(self, hex_data):
        """Analyze hex-encoded device status data"""
        logger.info("Hex Device Status Analysis:")
        logger.info("Full hex string: %s", hex_data)
        
        # Look for known patterns based on DiivooWT11W parsing
        patterns = {
            '19D8': 'Port 1 status pattern',
            '1AD8': 'Port 2 status pattern', 
            '1BD8': 'Port 3 status pattern',
            '21B7': 'Port 1 timer pattern',
            '22B7': 'Port 2 timer pattern',
            '23B7': 'Port 3 timer pattern',
            '25AD': 'Port 1 duration pattern',
            '26AD': 'Port 2 duration pattern',
            '27AD': 'Port 3 duration pattern',
        }
        
        found_patterns = []
        for pattern, description in patterns.items():
            pos = hex_data.find(pattern)
            if pos >= 0:
                found_patterns.append((pattern, description, pos))
                logger.info("  → Found %s at position %d", description, pos)
                
                # Extract the full pattern with data
                if pos + 6 <= len(hex_data):
                    full_pattern = hex_data[pos:pos + 6]
                    logger.info("    Full pattern: %s", full_pattern)
                    
                    # For status patterns, decode the status
                    if 'status' in description:
                        status_code = full_pattern[2:]  # Last 4 chars
                        status_meanings = {
                            'D821': 'ON',
                            'D820': 'OFF (Recent)',
                            'D800': 'OFF (Idle)'
                        }
                        if status_code in status_meanings:
                            logger.info("    Status meaning: %s", status_meanings[status_code])
                    
                    # For timer patterns, extract timer value
                    elif 'timer' in description and pos + 12 <= len(hex_data):
                        timer_hex = hex_data[pos + 4:pos + 12]  # 8 hex chars after pattern
                        try:
                            timer_value = int(timer_hex, 16)
                            logger.info("    Timer value: %d seconds", timer_value)
                        except ValueError:
                            logger.info("    Timer hex: %s (could not convert)", timer_hex)
                    
                    # For duration patterns
                    elif 'duration' in description and pos + 8 <= len(hex_data):
                        duration_hex = hex_data[pos + 4:pos + 8]  # 4 hex chars after pattern
                        try:
                            duration_value = int(duration_hex, 16)
                            logger.info("    Duration value: %d", duration_value)
                        except ValueError:
                            logger.info("    Duration hex: %s (could not convert)", duration_hex)
        
        if not found_patterns:
            logger.info("  → No known patterns found, raw hex analysis:")
            # Break into chunks for easier reading
            chunk_size = 8
            for i in range(0, len(hex_data), chunk_size):
                chunk = hex_data[i:i + chunk_size]
                logger.info("    Chunk %d: %s", i // chunk_size, chunk)

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        if rc == 0:
            logger.info("MQTT disconnected cleanly (code %s)", rc)
        else:
            logger.warning("MQTT disconnected unexpectedly with code %s", rc)
        self.mqtt_connected = False

    def disconnect_mqtt(self):
        """Disconnect from MQTT broker"""
        logger.info("Disconnecting from MQTT broker")
        with self._mqtt_lock:
            if self.mqtt_client:
                logger.debug("Stopping MQTT loop")
                self.mqtt_client.loop_stop()
                logger.debug("Disconnecting MQTT client")
                self.mqtt_client.disconnect()
                self.mqtt_client = None
                self.mqtt_connected = False
                logger.info("MQTT disconnected and cleaned up")
            else:
                logger.debug("No MQTT client to disconnect")

    def add_status_callback(self, callback: Callable):
        """Add a callback for device status updates"""
        if callback not in self.status_callbacks:
            self.status_callbacks.append(callback)

    def remove_status_callback(self, callback: Callable):
        """Remove a callback for device status updates"""
        if callback in self.status_callbacks:
            self.status_callbacks.remove(callback)

    def is_subscription_expired(self) -> bool:
        """Check if MQTT subscription is expired or about to expire."""
        if not self.subscription_data:
            return True
            
        expire_timestamp = self.subscription_data.get('expire')
        if not expire_timestamp:
            return True
            
        # Check if subscription expires in the next 5 minutes (300 seconds)
        current_time = datetime.utcnow().timestamp() * 1000  # Convert to milliseconds
        time_until_expiry = expire_timestamp - current_time
        
        return time_until_expiry <= 300000  # 5 minutes in milliseconds

    def renew_subscription(self) -> bool:
        """Renew the MQTT subscription if it's expired or about to expire."""
        if not self.is_subscription_expired():
            return True
            
        if not self._subscription_devices or not self._subscription_hids:
            logger.warning("Cannot renew subscription: missing device or HID data")
            return False
            
        logger.info("Renewing MQTT subscription")
        
        # Disconnect existing MQTT connection
        self.disconnect_mqtt()
        
        # Re-subscribe with stored parameters
        primary_hid = self._subscription_hids[0]
        result = self.subscribe_to_device_status(
            primary_hid,
            self._subscription_hids,
            self._subscription_devices
        )
        
        if result:
            logger.info("MQTT subscription renewed successfully")
            return True
        else:
            logger.error("Failed to renew MQTT subscription")
            return False
