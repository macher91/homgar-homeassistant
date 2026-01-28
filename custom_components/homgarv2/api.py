import binascii
import hashlib
import hmac
import os
import json
import threading
import uuid
import logging
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
        self._api_cmd_counter = 0
        self._mqtt_msg_counter = 0

    def _request(self, method, url, with_auth=True, headers=None, **kwargs):
        # --- ORIGINAL LOGIC UNCHANGED ---
        headers = {"lang": "en", "appCode": "1", **(headers or {})}
        if with_auth:
            headers["auth"] = self.cache.get("token")
        response = self.session.request(method, url, headers=headers, **kwargs)
        # --------------------------------

        # --- ONLY ADDITION: HEX LOGGING (DISABLED) ---
        # if "/app/device/getDeviceStatus" in url:
        #     try:
        #         # Convert raw bytes to hex string
        #         hex_data = ' '.join(f"{b:02X}" for b in response.content)
        #         logger.info("[HTTP-POLL-HEX] Raw HEX: %s", hex_data)
        #         # Show raw string text
        #         logger.info("[HTTP-POLL-HEX] Raw Text: %s", response.text)
        #     except Exception as e:
        #         logger.error("Hex logging failed: %s", e)
        # ---------------------------------

        # --- ORIGINAL LOGIC UNCHANGED ---
        logger.debug("[API HTTP RECV] Status: %d | URL: %s", response.status_code, url)
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
        return "push_product_key_placeholder"
    
    def _post_json(self, path, body, **kwargs):
        return self._request_json("POST", path, json=body, **kwargs)

    def login(self, email: str, password: str, area_code="31") -> None:
        dev_id = binascii.b2a_hex(os.urandom(16)).decode('utf-8')
        data = self._post_json("/auth/basic/app/login", {
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
            "deviceId": dev_id
        }, with_auth=False)
        self.cache['email'] = email
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.utcnow().timestamp() + data.get('tokenExpired')
        self.cache['refresh_token'] = data.get('refreshToken')

    def get_homes(self) -> List[HomgarHome]:
        data = self._get_json("/app/member/appHome/list")
        return [HomgarHome(hid=h.get('hid'), name=h.get('homeName')) for h in data]

    def get_devices_for_hid(self, hid: str) -> List[HomgarHubDevice]:
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
            return MODEL_CODE_MAPPING.get(model_code)

        for hub_data in data:
            subdevices = []
            for sub_data in hub_data.get('subDevices', []):
                sub_cls = get_device_class(sub_data)
                if sub_cls:
                    props = device_base_props(sub_data)
                    props.update({'hub_device_name': hub_data.get('deviceName'), 'hub_product_key': hub_data.get('productKey')})
                    subdevices.append(sub_cls(**props))
            hub_cls = get_device_class(hub_data) or HomgarHubDevice
            hub_props = device_base_props(hub_data)
            hub_props.update({'hub_device_name': hub_data.get('deviceName'), 'hub_product_key': hub_data.get('productKey')})
            hubs.append(hub_cls(**hub_props, subdevices=subdevices))
        return hubs

    def get_device_status(self, hub: HomgarHubDevice) -> None:
        data = self._get_json("/app/device/getDeviceStatus", params={"mid": str(hub.mid)})
        id_map = {sid: dev for dev in [hub, *hub.subdevices] for sid in dev.get_device_status_ids()}
        for status in data.get('subDeviceStatus', []):
            dev_id = status.get('id')
            device = id_map.get(dev_id)
            if device:
                device.set_device_status(status)

    def control_device_work_mode(self, device_name: str, product_key: str, mid: str, addr: int, port: int, mode: int, duration: int = 0) -> dict:
        self._api_cmd_counter += 1
        seq = self._api_cmd_counter
        logger.info("MQTT-CMD: Outbound #%d | Zone %d | Mode %d", seq, port, mode)
        return self._post_json("/app/device/controlWorkMode", {
            "deviceName": device_name, "productKey": product_key, "mid": str(mid),
            "addr": addr, "port": port, "mode": mode, "duration": duration, "param": str(seq)
        })

    def ensure_logged_in(self, email: str, password: str, area_code: str = "31") -> None:
        exp = self.cache.get('token_expires', 0)
        if self.cache.get('email') != email or (datetime.fromtimestamp(exp) - datetime.utcnow() < timedelta(minutes=60)):
            self.login(email, password, area_code)

    def subscribe_to_device_status(self, hid: str, hid_list: List[str], devices: List[dict]) -> Optional[dict]:
        if mqtt is None: return None
        device_id = binascii.b2a_hex(os.urandom(10)).decode('utf-8')
        sub_body = {
            "hid": hid, "hidList": hid_list, "subscribe": devices, "unsubscribe": [],
            "userInfo": {
                "deviceName": device_id, "deviceType": 1, "notice": 0,
                "productKey": self._get_push_product_key(), "pushId": str(uuid.uuid4()).replace('-', '')
            }
        }
        try:
            logger.info("Requesting MQTT credentials for HID: %s", hid)
            self.subscription_data = self._post_json("/app/device/subscribeStatus", sub_body)
            #CONFIRM THE EXPIRATION TIME
            logger.info("[DIAG] [MQTT-EXPIRE] Raw Expire: %s", self.subscription_data.get('expire'))
            #
            self._subscription_devices, self._subscription_hids = devices, hid_list
            logger.info("[DEBUG] [API HTTP RECV] Status: 200 | URL: %s/app/device/subscribeStatus", self.base)
            return self.subscription_data
        except Exception as e:
            logger.error("MQTT Subscription failure: %s", e)
            return None

    def connect_mqtt(self, callback: Optional[Callable] = None) -> bool:
        if not self.subscription_data or mqtt is None: return False

        # --- FIX 1: Add Gatekeeper to prevent double connections ---
        if self.mqtt_connected and self.mqtt_client and self.mqtt_client.is_connected():
            return True

        # --- FIX 2: Prevent duplicate callbacks (stops 18x log lines) ---
        if callback and callback not in self.status_callbacks:
            self.status_callbacks.append(callback)

        with self._mqtt_lock:
            if self.mqtt_client and self.mqtt_connected: return True
            try:
                c = self.subscription_data
                dn, pk, ds = c.get('deviceName'), c.get('productKey'), c.get('deviceSecret')
                client_id = f"{dn}|securemode=3,signmethod=hmacsha1|"
                username = f"{dn}&{pk}"
                sign_content = f"clientId{dn}deviceName{dn}productKey{pk}"
                password = hmac.new(ds.encode('utf-8'), sign_content.encode('utf-8'), hashlib.sha1).hexdigest().upper()

                self.mqtt_client = mqtt.Client(client_id=client_id, clean_session=True, protocol=mqtt.MQTTv311)
                self.mqtt_client.on_connect, self.mqtt_client.on_message = self._on_mqtt_connect, self._on_mqtt_message


                # --- FIX 3: REMOVED self.mqtt_client.on_log to stop duplicate logs ---
                self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
                # self.mqtt_client.on_log = self._on_mqtt_log  <-- COMMENT THIS OUT

                self.mqtt_client.on_subscribe = self._on_mqtt_subscribe
                
                self.mqtt_client.username_pw_set(username, password)
                self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
                
                
                h, p = c.get('mqttHostUrl').split(':') if ':' in c.get('mqttHostUrl') else (c.get('mqttHostUrl'), 1883)
                logger.info("[DIAG] [MQTT-SIGN] Sending Signed Connect to %s", h)
                self.mqtt_client.connect(h, int(p), keepalive=120)
                self.mqtt_client.loop_start()
                return True
            except Exception as e:
                logger.error("MQTT Connection Exception: %s", e)
                return False
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.mqtt_connected = True
            pk = self.subscription_data.get('productKey')
            dn = self.subscription_data.get('deviceName')
            
            # These topics use the specific Aliyun hierarchy for your Hub and its Sub-devices
            topics = [
                (f"/sys/{pk}/{dn}/thing/event/property/post", 0),
                (f"/sys/{pk}/{dn}/thing/service/property/set", 0),
                (f"/sys/{pk}/{dn}/thing/status/update", 0),
                (f"/sys/{pk}/{dn}/thing/event/+/post", 0),
                (f"/sys/{pk}/{dn}/thing/event/property/post_reply", 0),
                (f"/sys/{pk}/{dn}/thing/event/property/batch/post", 0),
                (f"/sys/{pk}/{dn}/thing/sub/status/update", 0),
                (f"/sys/{pk}/{dn}/thing/sub/event/property/post", 0),
                (f"/sys/{pk}/{dn}/thing/service/+/reply", 0)
            ]
            
            client.subscribe(topics)
            logger.info("[DIAG] [MQTT-INTERNAL] Sending SUBSCRIBE %s", topics)
            logger.info("MQTT: SUCCESS - Connected. Listening for Hub/Sub-device commands and telemetry.")
        else:
            self.mqtt_connected = False
            logger.error("MQTT: Connection refused code %d", rc)    


    def _on_mqtt_subscribe(self, client, userdata, mid, granted_qos):
        logger.info("[DIAG] [MQTT-SUBACK] MessageID=%d | GrantedQoS=%s", mid, granted_qos)
    
    def _on_mqtt_log(self, client, userdata, level, buf):
        logger.info("[DIAG] [MQTT-INTERNAL] %s", buf)
    
    def _on_mqtt_message(self, client, userdata, msg):
        self._mqtt_msg_counter += 1
        seq = self._mqtt_msg_counter
        try:
            payload = msg.payload.decode('utf-8')
            logger.info("[DIAG] [MQTT-INTERNAL] Received PUBLISH (d0, q0, r0, m0), '%s', ...  (%d bytes)", msg.topic, len(payload))
            logger.info("MQTT: Real-time update #%d received on topic: %s", seq, msg.topic)
            data = json.loads(payload)
            data['_seq'] = seq
            if 'params' in data: data.setdefault('data', data['params'])
            for cb in self.status_callbacks:
                try: cb(data)
                except Exception as e: logger.error("Callback Error: %s", e)
        except Exception as e:
            logger.error("MQTT Message Error: %s", e)

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        logger.warning("[DIAG] [MQTT-DISCONN] RC=%d | Time=%s", rc, time.strftime("%H:%M:%S"))
        if rc != 0: logger.warning("MQTT: Connection lost. Reconnecting...")

    def disconnect_mqtt(self):
        with self._mqtt_lock:
            if self.mqtt_client:
                logger.info("[DIAG] [MQTT-STOP] Shutting down client and loop.")
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                self.mqtt_client = None
                self.mqtt_connected = False

    def is_subscription_expired(self) -> bool:
        if not self.subscription_data: return True
        exp = self.subscription_data.get('expire', 0)
        return (exp - int(time.time() * 1000)) <= 60000

    #def renew_subscription(self) -> bool:
    #    if not self.is_subscription_expired(): return True
    #    self.disconnect_mqtt()
    #    return bool(self.subscribe_to_device_status(self._subscription_hids[0], self._subscription_hids, self._subscription_devices))

    def renew_subscription(self) -> bool:
        if not self.is_subscription_expired(): return True
        # REMOVED: self.disconnect_mqtt() 
        return bool(self.subscribe_to_device_status(self._subscription_hids[0], self._subscription_hids, self._subscription_devices))