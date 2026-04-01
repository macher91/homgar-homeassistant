import binascii
import hashlib
import os
import json
import threading
import uuid
import hmac
import time
from datetime import datetime, timedelta
from typing import Optional, List, Callable

import requests
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from .devices import HomgarHome, MODEL_CODE_MAPPING, HomgarHubDevice
from .logutil import TRACE, get_logger

logger = get_logger(__name__)


class HomgarApiException(Exception):
    def __init__(self, code, msg, data=None):
        super().__init__()
        self.code = code
        self.msg = msg
        self.data = data

    def __str__(self):
        s = f"HomGar API returned code {self.code}"
        if self.msg:
            s += f": {self.msg}"
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
        
        # Configure retries for the session
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.cache = auth_cache or {}
        self.base = api_base_url
        self.mqtt_client = None
        self.mqtt_connected = False
        self.status_callbacks = []
        self.on_disconnect_callback = None
        self._mqtt_connecting = False
        self.subscription_data = None
        self._mqtt_lock = threading.Lock()
        self._subscription_devices = []
        self._subscription_hids = []

    def _request(self, method, url, with_auth=True, headers=None, **kwargs):
        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        
        # Primary base headers requested by user
        base_headers = {
            "lang": "en",
            "version": "2.21.2075",
            "appCode": "1",
            "sceneType": "1",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "okhttp/4.9.2"
        }
        
        # Try to include HID if we have it
        hid = kwargs.get('params', {}).get('hid') or kwargs.get('json', {}).get('hid')
        if not hid and hasattr(self, '_last_hid'):
            hid = self._last_hid
    
        if hid:
            base_headers["hid"] = str(hid)
            
        headers = {**base_headers, **(headers or {})}
        
        if with_auth and "token" in self.cache:
            headers["auth"] = self.cache["token"]
            
        # Set a default timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = 10
            
        try:
            response = self.session.request(method, url, headers=headers, **kwargs)
            logger.log(TRACE, "-[%03d]-> %s", response.status_code, response.text)
            return response
        except requests.exceptions.RequestException as e:
            logger.error("Network error during HomGar API request (%s %s): %s", method, url, e)
            raise HomgarApiException(-1, str(e))

    def _request_json(self, method, path, **kwargs):
        resp_obj = self._request(method, self.base + path, **kwargs)
        
        try:
            response = resp_obj.json()
        except requests.exceptions.JSONDecodeError:
            logger.error("Failed to parse JSON response from HomGar API (%s %s). Status: %s, Text: %s", 
                        method, path, resp_obj.status_code, resp_obj.text[:200])
            raise HomgarApiException(-1, f"Invalid JSON response (Status {resp_obj.status_code})")
            
        code = response.get('code')
        if code != 0:
            logger.error(
                "HomGar API error code %s on %s %s with kwargs: %s | response: %s",
                code, method, path, kwargs, response
            )
            raise HomgarApiException(code, response.get('msg'), response.get('data'))
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
        user_data = data.get('user', {})
        self.cache['email'] = email
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.utcnow().timestamp() + data.get('tokenExpired')
        self.cache['refresh_token'] = data.get('refreshToken')
        self.cache['mqtt_host'] = data.get('mqttHostUrl')
        self.cache['v_device_name'] = user_data.get('deviceName')
        self.cache['v_device_secret'] = user_data.get('deviceSecret')
        self.cache['v_product_key'] = user_data.get('productKey')
        
        # DEBUG: Inspect the structure to find the real virtual device ID
        safe_user_data = {k: ("***" if "secret" in k.lower() or "password" in k.lower() else v) for k, v in user_data.items()}
        logger.debug("LOGIN RESPONSE USER DATA KEYS: %s", list(user_data.keys()))
        logger.debug("LOGIN RESPONSE USER DATA (SAFE): %s", safe_user_data)
        logger.debug("Logged in and stored Virtual Device ID: %s", self.cache.get('v_device_name'))

    def get_homes(self) -> List[HomgarHome]:
        """
        Retrieves all HomgarHome objects associated with the logged in account.
        Requires first logging in.
        :return: List of HomgarHome objects
        """
        data = self._get_json("/app/member/appHome/list")
        homes = [HomgarHome(hid=h.get('hid'), name=h.get('homeName')) for h in data]
        if homes and not hasattr(self, '_last_hid'):
            self._last_hid = homes[0].hid
        return homes

    def get_devices_for_hid(self, hid: str) -> List[HomgarHubDevice]:
        """
        Retrieves a device tree associated with the home identified by the given hid (home ID).
        This function returns a list of hubs associated with the home. Each hub contains associated
        subdevices that use the hub as gateway.
        :param hid: The home ID to retrieve hubs and associated subdevices for
        :return: List of hubs with associated subdevicse
        """
        self._last_hid = hid
        data = self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})
        hubs = []

        logger.debug("=== RAW DEVICE TREE FOR HID %s ===", hid)
        logger.debug(json.dumps(data, indent=2))


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
            logger.debug(
                "HUB FOUND: name=%s model=%s modelCode=%s did=%s",
                hub_data.get("deviceName"),
                hub_data.get("model"),
                hub_data.get("modelCode"),
                hub_data.get("did")
            )

            hub_did = hub_data.get("did")  # 🔑 DID réel du hub

            subdevices = []
            for subdevice_data in hub_data.get('subDevices', []):
                logger.debug(
                    "  SUBDEVICE FOUND: name=%s model=%s modelCode=%s did=%s",
                    subdevice_data.get("name"),
                    subdevice_data.get("model"),
                    subdevice_data.get("modelCode"),
                    subdevice_data.get("did")
                )

                did = subdevice_data.get('did')

                # ⚠️ Correction HomGar : le subdevice météo a did = "0"
                if str(did) == "0":
                    logger.debug(
                        "  SUBDEVICE '%s' has did=0 → binding to hub did=%s",
                        subdevice_data.get("name"),
                        hub_did
                    )
                    subdevice_data = dict(subdevice_data)  # copie pour ne pas polluer l'original
                    subdevice_data["did"] = hub_did

                # Ancien cas spécial (hub display), on ne change pas
                if did == 1:
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

            hubs.append(
                hub_class(
                    **hub_props,
                    subdevices=subdevices
                )
            )

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
            "hid": str(self._last_hid) if hasattr(self, '_last_hid') else "123456",
            "deviceName": device_name,
            "productKey": product_key,
            "mid": str(mid),
            "addr": addr,
            "port": port,
            "mode": mode,
            "duration": duration,
            "param": ""
        }, headers={"Connection": "close"})

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
                "deviceName": self.cache.get('v_device_name', device_id),
                "deviceType": 1,
                "notice": 0,
                "productKey": self.cache.get('v_product_key', self._get_push_product_key()),
                "pushId": str(uuid.uuid4()).replace('-', '')
            }
        }
        
        try:
            logger.debug("Sending subscription request to API, payload: %s", subscribe_data)
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
            
        if callback and callback not in self.status_callbacks:
            self.status_callbacks.append(callback)
            logger.debug("Added status callback (total callbacks: %d)", len(self.status_callbacks))
            
        with self._mqtt_lock:
            if self._mqtt_connecting or (self.mqtt_client and self.mqtt_connected):
                logger.debug("MQTT already connecting or connected")
                return True
                
            self._mqtt_connecting = True
                
            try:
                # Get credentials and broker info first to avoid NameError
                # NEW ARCHITECTURE: Use Virtual Device (Observer) credentials from login
                v_device_name = self.cache.get('v_device_name')
                v_device_secret = self.cache.get('v_device_secret')
                v_product_key = self.cache.get('v_product_key')
                mqtt_url = self.cache.get('mqtt_host') or self.subscription_data.get('mqttHostUrl', '')
                
                # Physical device info strictly for topic paths
                p_device_name = self.subscription_data.get('deviceName')
                p_product_key = self.subscription_data.get('productKey')
                
                if not v_device_name or not v_device_secret or not v_product_key:
                    logger.error("Missing Virtual Device credentials in cache. Ensure login was successful.")
                    self._mqtt_connecting = False
                    return False

                # Aliyun MQTT Signature calculation (Observer Mode)
                # Timestamp in milliseconds
                timestamp_ms = str(int(time.time() * 1000))
                
                # Format: {clientId}|securemode=2,signmethod=hmacsha1,timestamp={ms}|
                mqtt_client_id = f"{v_device_name}|securemode=2,signmethod=hmacsha1,timestamp={timestamp_ms}|"
                
                # Content for signing: clientId{id}deviceName{id}productKey{key}timestamp{ms}
                # Architecture note: clientId and deviceName in the content string must be the Virtual ID
                sign_content = f"clientId{v_device_name}deviceName{v_device_name}productKey{v_product_key}timestamp{timestamp_ms}"
                mqtt_password = hmac.new(
                    v_device_secret.encode('utf-8'),
                    sign_content.encode('utf-8'),
                    hashlib.sha1
                ).hexdigest()
                
                mqtt_username = f"{v_device_name}&{v_product_key}"

                logger.info("=== MQTT CALCULATED VIRTUAL CREDENTIALS ===")
                logger.info("Host: %s", mqtt_url)
                logger.info("Virtual Client ID: %s", mqtt_client_id)
                logger.info("Virtual Username: %s", mqtt_username)
                
                # Topics must use the VIRTUAL device information for the Observer session
                self._monitored_topics = [
                    f"/{v_product_key}/{p_device_name}/user/status",
                    f"/{v_product_key}/{p_device_name}/user/get",
                    f"/{v_product_key}/{p_device_name}/user/update",
                    f"/sys/{v_product_key}/{p_device_name}/thing/event/property/post",
                    f"/sys/{v_product_key}/{p_device_name}/thing/service/property/set",
                    f"/sys/{v_product_key}/{p_device_name}/thing/status/update",
                    f"/sys/{v_product_key}/{p_device_name}/thing/sub/event/property/post",
                    f"/sys/{v_product_key}/{p_device_name}/thing/sub/status/update"
                ]
                
                logger.info("Planned MQTT subscriptions to PHYSICAL device (%d topics):", len(self._monitored_topics))
                for t in self._monitored_topics:
                    logger.info(" - %s", t)
                
                if ':' in mqtt_url:
                    host, port = mqtt_url.split(':')
                    port = int(port)
                else:
                    host = mqtt_url
                    port = 1883
                
                # Detect paho-mqtt version and handle CallbackAPIVersion for 2.0+
                import paho.mqtt as paho_root
                logger.info("Detected paho-mqtt version: %s", getattr(paho_root, "__version__", "unknown"))
                
                api_version = None
                try:
                    from paho.mqtt.enums import CallbackAPIVersion
                    api_version = CallbackAPIVersion.VERSION2
                    logger.debug("Using CallbackAPIVersion.VERSION2 for paho-mqtt 2.0+")
                except ImportError:
                    logger.debug("paho-mqtt version < 2.0, CallbackAPIVersion not required")

                logger.debug("Creating MQTT client")
                if api_version:
                    # paho-mqtt 2.0+ constructor
                    self.mqtt_client = mqtt.Client(api_version, mqtt_client_id)
                else:
                    # paho-mqtt 1.0 constructor
                    self.mqtt_client = mqtt.Client(mqtt_client_id)
                
                # Add internal diagnostic logging
                self.mqtt_client.on_log = self._on_mqtt_log
                
                self.mqtt_client.on_connect = self._on_mqtt_connect
                self.mqtt_client.on_message = self._on_mqtt_message
                self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
                
                # Set credentials
                self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
                logger.info("MQTT credentials set and signed using HMAC-SHA1")
                
                # Connect to broker
                mqtt_url = self.subscription_data.get('mqttHostUrl', '')
                if ':' in mqtt_url:
                    host, port = mqtt_url.split(':')
                    port = int(port)
                else:
                    host = mqtt_url
                    port = 1883
                    
                logger.info("Connecting to MQTT broker at %s:%d", host, port)
                
                try:
                    self.mqtt_client.connect(host, port, 60)
                    self.mqtt_client.loop_start()
                    logger.debug("MQTT loop started successfully")
                    return True
                except Exception as connect_error:
                    logger.error("MQTT connect() failed: %s", connect_error)
                    self._mqtt_connecting = False
                    self.mqtt_connected = False
                    return False
                
            except Exception as e:
                logger.error("Failed to setup MQTT client: %s", e)
                # Ensure we reset flags on setup failure too
                self._mqtt_connecting = False
                self.mqtt_connected = False
                return False

    def _on_mqtt_log(self, client, userdata, level, buf):
        """Internal MQTT client diagnostic logging"""
        logger.debug("[MQTT LOG] %s", buf)

    def _on_mqtt_connect(self, client, userdata, flags, rc, *args, **kwargs):
        """MQTT connection callback - Robust for V1 and V2"""
        # In V2 rc is positional index 3 (if self is 0), but paho passes it as 4th arg
        # In V1 rc is positional index 3.
        # Let's just use the 'rc' argument name which is common, but paho 2.x might use reason_code
        reason_code = getattr(rc, "value", rc)
        logger.info("MQTT connection callback triggered. Reason: %s", reason_code)
        
        if reason_code == 0:
            logger.info("MQTT connected successfully")
            self.mqtt_connected = True
            self._mqtt_connecting = False
            
            # Subscribe to all planned topics
            if hasattr(self, '_monitored_topics') and self._monitored_topics:
                for topic in self._monitored_topics:
                    result = client.subscribe(topic)
                    logger.info("Subscribed to MQTT topic: %s (result code: %s)", topic, result)
            else:
                logger.error("No monitored topics defined for subscription")
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
            self._mqtt_connecting = False

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.info("=== MQTT MESSAGE RECEIVED ===")
            logger.info("Topic: %s | Payload: %s", topic, payload)
            
            # Try to parse as JSON
            try:
                data = json.loads(payload)
                
                # Adaptation for Aliyun/V2 format: {"params": {"param": "#P...|{json}|...#"}}
                if 'params' in data and isinstance(data['params'], dict):
                    params = data['params']
                    
                    # Check for nested #P format
                    if 'param' in params and isinstance(params['param'], str) and params['param'].startswith('#P'):
                        logger.info("Detected nested #P payload format - extracting inner data")
                        try:
                            # Format is: #P[prefix_info]|[json_data]|[timestamp]|[maybe_more]#
                            parts = params['param'].split('|')
                            if len(parts) >= 2:
                                # Extract device ID from the prefix if possible. 
                                # It seems to be the last part of parts[0] (e.g. ...11654321)
                                raw_prefix = parts[0]
                                mid = None
                                # Try to find a numeric ID at the end of the prefix
                                import re
                                match = re.search(r'(\d{5,})$', raw_prefix)
                                if match:
                                    raw_id = match.group(1)
                                    # Heuristic: if the ID is very long, it likely contains a timestamp. 
                                    # The actual 'mid' is usually the last 6 digits.
                                    mid = raw_id[-6:] if len(raw_id) > 10 else raw_id
                                    logger.debug("Extracted mid from #P prefix: %s (raw was %s)", mid, raw_id)
                                
                                # Parse the inner JSON data
                                inner_json_str = parts[1]
                                inner_data = json.loads(inner_json_str)
                                
                                # Process inner data
                                for key, val in inner_data.items():
                                    # Extract value if it's a dict with 'value' key
                                    actual_val = val.get('value') if isinstance(val, dict) and 'value' in val else val
                                    
                                    adapted_update = {
                                        "id": key,
                                        "value": actual_val,
                                        "mid": mid,
                                        "deviceId": mid  # Use the clean numeric string for matching
                                    }
                                    
                                    for i, callback in enumerate(self.status_callbacks):
                                        try:
                                            callback(adapted_update)
                                        except Exception as callback_error:
                                            logger.error("Error in callback %d for #P update: %s", i, callback_error)
                                return # Successfully processed nested format
                        except Exception as p_error:
                            logger.error("Failed to parse nested #P payload: %s", p_error)

                    # Fallback to standard Aliyun V2 processing
                    logger.info("Processing standard Aliyun/V2 payload")
                    device_id = data.get('deviceId') or data.get('mid')
                    
                    for key, val in params.items():
                        actual_val = val.get('value') if isinstance(val, dict) and 'value' in val else val
                        adapted_update = {
                            "id": key,
                            "value": actual_val,
                            "deviceId": device_id,
                            "mid": device_id
                        }
                        
                        for i, callback in enumerate(self.status_callbacks):
                            try:
                                callback(adapted_update)
                            except Exception as callback_error:
                                logger.error("Error in callback %d for adapted update: %s", i, callback_error)
                    return

                # Standard format processing
                for i, callback in enumerate(self.status_callbacks):
                    try:
                        callback(data)
                    except Exception as callback_error:
                        logger.error("Error in callback %d: %s", i, callback_error)
                        
            except json.JSONDecodeError as json_error:
                logger.debug("Failed to parse MQTT as JSON (might be expected for raw hex payloads): %s", json_error)
                
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e)
    


    def _on_mqtt_disconnect(self, client, userdata, *args, **kwargs):
        """MQTT disconnect callback - Robust for V1 and V2"""
        # In V1, rc is the 3rd positional arg (client, userdata, rc) -> args[0]
        # In V2, reason_code is the 4th positional arg (client, userdata, flags, reason_code, properties) -> args[1]
        rc = None
        if len(args) > 1: # Likely V2: (flags, reason_code, properties)
            rc = args[1]
        elif len(args) > 0: # Likely V1: (rc,)
            rc = args[0]
            
        reason_code = getattr(rc, "value", rc)
        if reason_code == 0:
            logger.info("MQTT disconnected cleanly (code %s)", reason_code)
        else:
            logger.warning("MQTT disconnected unexpectedly with code %s", reason_code)
        
        self.mqtt_connected = False
        self._mqtt_connecting = False
        if self.on_disconnect_callback:
            try:
                self.on_disconnect_callback(rc)
            except Exception as e:
                logger.error("Error in on_disconnect_callback: %s", e)

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

    def renew_subscription(self, force: bool = False, disconnect: bool = True) -> bool:
        """Renew the MQTT subscription if it's expired or about to expire, or if force=True."""
        if not force and not self.is_subscription_expired():
            return True
            
        if not self._subscription_devices or not self._subscription_hids:
            logger.warning("Cannot renew subscription: missing device or HID data")
            return False
            
        logger.info("Renewing MQTT subscription (force=%s, disconnect=%s)", force, disconnect)
        
        # Disconnect existing MQTT connection only if requested
        if disconnect:
            self.disconnect_mqtt()
        
        # Re-subscribe with stored parameters
        primary_hid = min(self._subscription_hids)
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
