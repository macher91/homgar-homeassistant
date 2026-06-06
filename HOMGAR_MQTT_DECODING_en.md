# HomGar / Baldr — Device Status Decoding (MQTT / CoAP / HTTP)

Result of reverse-engineering the APK `com_baldr_homgar_v2.22.2080`. Covers irrigation
controllers (e.g. **HTV0537FRF**, **Diivoo WT-11W**) and documents how a raw hex string
from the cloud turns into named, human-readable channel values.

## Table of contents
1. [MQTT message path](#1-mqtt-message-path)
2. [Transport frame `#P…`](#2-transport-frame-p)
3. [DP TLV format (channel payload)](#3-dp-tlv-format-channel-payload)
4. [Channel type enum (`b4/B`)](#4-channel-type-enum-b4b)
5. [Time fields — T4Date format](#5-time-fields--t4date-format)
6. [Channel-to-port mapping](#6-channel-to-port-mapping)
7. [What is hardcoded in the APK vs. what comes from the API](#7-what-is-hardcoded-in-the-apk-vs-what-comes-from-the-api)
8. [Decoded examples](#8-decoded-examples)
9. [Ready-to-use decoder (Python)](#9-ready-to-use-decoder-python)
10. [Source file map](#10-source-file-map)

---

## 1. MQTT message path

Chain: **MQTT bytes → JSON → param string → `#P…` frame → hex → byte[] → bit fields**.

1. **Receive** — `AliMqttService$initListener$1.onNotify` (Alibaba Linkkit):
   `AMessage.data` → `byte[]` → UTF-8 `String` → Gson → `AliMqttMsg`.
2. The interesting payload is `msg.getParams().getParam()` — a **String** (`Params.param`),
   passed to `AliMqttService.dealMQTTMsg(String)`.
3. Messages are then dispatched via **EventBus** (`Ib/d->e`) as `EventMsg`
   (e.g. `UPDATE_STATUS_CHANGE`) and update the cache in `Business`.

> The format is identical for payloads from **CoAP** (`libcoap.so`, `/app/device/coap/state`)
> and from **HTTP** — all of them reach the same DP decoder.

---

## 2. Transport frame `#P…`

Some payloads are wrapped in a fixed-offset ASCII frame. Handled only when it starts
with `#P`, ends with `#`, and has length > 27.

| Offset `[from,to)` | Meaning | Decoding |
|---|---|---|
| `2..14`  | timestamp | `parseLong` (base-10) |
| `14..24` | target UID | `parseLong`; dropped if ≠ `Business.getUID()` |
| `24..26` | **message type** | `parseInt(s, 16)` |
| `26..len-1` | body | split by type |

The type drives two `packed-switch` tables: `0x00–0x06` and `0x80–0x84`; `0x08` is the
"feedback" branch. Body is split on `|`.

The format observed in real MQTT messages (the `value` field) has a simpler prefix:

```
"11#17E1BB00...FE..."
 └┬┘ └──────── DP TLV (hex) ────────┘
  └ counter/sequence (stripped before parsing the hex)
```

---

## 3. DP TLV format (channel payload)

Parser: `DpDeviceStatus$Companion.analyzeDpDeviceStatus(String, boolean)` →
converts hex to `byte[]` (every 2 chars = 1 byte, `parseInt(sub,16) & 0xFF`) →
`analyzeDpDeviceStats([B, model, …)`.

Each record: **`[dpId] [flag byte] [value…]`**, decoded byte by byte:

- **flag bit 7 == 0** → "short" record:
  - `typeCode = (flag >> 4) & 0x7`
  - length 1, the value *is* the flag byte (a packed/enum field)
- **flag bit 7 == 1** → "long" record:
  - `typeLen = (flag & 0x3) + 1`
  - `code5 = (flag >> 2) & 0x1F`
  - if `code5 ≤ 0x1E`: `typeCode = code5 + 8`, payload = `typeLen+1` bytes after the flag
  - if `code5 == 0x1F` (ext): the next byte is `typeCode = next + 0x27`, payload `typeLen+1` bytes
- **Multi-byte values are little-endian** (`ByteBuffer … LITTLE_ENDIAN`).

The `typeCode` decoded from the frame **equals** the `dpCode` from the DP model
(`DeviceStatus` compares `DpDeviceStatus.getTypeCode()` with `RecDeviceDpModel.getDpCode()`).

---

## 4. Channel type enum (`b4/B`)

Mapping `typeCode` → name (hardcoded in the APK, file `smali/b4/B.smali`):

| code | name | | code | name | | code | name |
|---|---|---|---|---|---|---|---|
| 0x00 | CHG | | 0x10 | CURRENT | | 0x22 | MAX_RH |
| 0x01 | RAIN | | 0x11 | POWER | | 0x23 | MAX_STATE_MOS |
| 0x02 | ALARM | | 0x12 | ENERGY | | 0x24 | MAX_WIND |
| 0x03 | CHECK | | 0x13 | **DURATION** | | 0x25 | WATER_ZONES |
| 0x08 | RM_TIME | | 0x14 | WATER_TOTAL | | 0x26 | TS_DET |
| 0x09 | TEM | | 0x15 | **EVENT_TIME** | | 0x27 | STA_VALVE |
| 0x0A | RH | | 0x16 | TREND | | 0x28 | STA_JOB |
| 0x0B | PH | | 0x17 | SENSOR_F | | 0x29 | STA_CALL |
| 0x0C | ATMOS | | 0x18 | V_WIND | | 0x2A | STA_WATER_PS |
| 0x0D | TOTAL_RAIN | | 0x19 | ILLUMINANCE | | 0x2B | HOUR_RAIN |
| 0x0E | V_FLOW | | 0x1A–0x1C | TOTAL_TODAY | | 0x2C | DAY_RAIN |
| 0x0F | LAST_USAGE | | 0x1D | VOLTAGE | | 0x2D | WEEK_RAIN |
| | | | 0x1E | WK_STATE | | 0x2E | STA_CUR_FLOW |
| | | | 0x1F | BAT | | | |
| | | | 0x20 | RSSI | | | |

Key ones for channel settings:
- **`0x13 DURATION`** — watering duration of a port (seconds)
- **`0x1E WK_STATE`** — port working state
- **`0x15 EVENT_TIME`** — time of the port's last event (T4Date format, see below)
- **`0x02 ALARM`** — port alarm flag
- **`0x20 RSSI`**, **`0x1F BAT`** — device telemetry

---

## 5. Time fields — T4Date format

> **Key finding:** `EVENT_TIME` and the `0xFE` field are **not a Unix timestamp**, but a
> **bit-packed date** decoded by `T4Date$Companion.getT4DateByParam(long)`.

A 32-bit value (little-endian from the payload), unpacked bitwise:

| field | bits | mask / op |
|---|---|---|
| second | 0–5 | `p & 0x3F` |
| minute | 6–11 | `(p >> 6) & 0x3F` |
| hour | 12–16 | `(p >> 12) & 0x1F` |
| day | 17–21 | `(p >> 17) & 0x1F` |
| month | 22–25 | `(p >> 22) & 0x0F` |
| year | 26–31 | `((p >> 26) & 0x3F) + 2020` |

(`0x7E4 = 2020` is the base year.) The time is **local to the device's timezone**.

**Control verification** (message with a known receive time):
- `value` of the `0xFE` field = `419369106` → T4Date = **2026-03-31 17:02:18**
- message `time` = `1774969338546` ms = **2026-03-31 15:02:18 UTC**
- Seconds/minutes match to the second; the +2 h difference = CEST timezone. ✔

The `0xFE` field (typeCode 54) = **the time the whole status frame was generated**
(always the freshest, independent of ports).

> Other contexts use other packing variants (all in `T4Date$Companion`):
> `getD2DateByParam` (watering plans), `getNextDateByTimeStamp` (schedule).
> The variant choice is **hardcoded per context**, it does not come from the API.

---

## 6. Channel-to-port mapping

Channels are grouped into **per-port triplets** (confirmed: EVENT_TIME = 0 exactly where
the port is inactive):

| port | DURATION (dpId) | WK_STATE (dpId) | EVENT_TIME (dpId) | ALARM (dpId) |
|---|---|---|---|---|
| **1** | 0x25 | 0x19 | 0x21 | 0x1D |
| **2** | 0x26 | 0x1A | 0x22 | 0x1E |
| **3** | 0x27 | 0x1B | 0x23 | 0x1F |

> The dpId → physical port link formally comes from the API (`RecDeviceDpModel.getDpPort()`).
> The ordering above (1,2,3) is inferred from observation and is consistent across all
> samples, but to be sure it should be confirmed with the `getDpList` spec of the model.

Values:
- **DURATION** in seconds: `600` = 10 min, `1680` = 28 min, `15000` = 250 min
- **WK_STATE** `33` (0x21 = `0b00100001`) = port active (bit0 + bit5)

---

## 7. What is hardcoded in the APK vs. what comes from the API

| Element | Source |
|---|---|
| TLV framing (dpId, flag, length) | **self-describing in the bytes** |
| `typeCode` → name (DURATION, EVENT_TIME…) | **enum `b4/B` in the APK** (static) |
| Date format / unpacking (T4Date) | **hardcoded** per context |
| Physical port number for a dpId (`dpPort`) | **API** (`getDpList`) |
| Divisor / unit (`decimal`, `unit`) | **API** (`RecDeviceDpSpec`) |
| Bit map / enums for mask-type fields (`mask`, `bit`, `enums`) | **API** (`RecDeviceDpSpec`) |

**Conclusion:** the entire decoding mechanism (how to lay out the bytes, how to unpack the
date) is in the APK and is static. The API only provides the **per-dpId semantics** —
assigning a channel to a port and its scale/unit. The values in the samples (600 = seconds)
came out consistent, so `decimal` for these controllers is most likely 0, but this is
formally confirmed only by the `getDpList` spec.

Fields provided by the API:
- **`RecDeviceDpModel`**: `dpId`, `dpCode` (= typeCode), `dpPort`, `dpType`, `endpoint`
- **`RecDeviceDpSpec`**: `length`, `dataType`/`dataTypeSub`, `decimal`, `unit`, `mask`,
  `bit`, `enums`, `min`/`max`, `step`

---

## 8. Decoded examples

### HTV0537FRF (2 ports) — `11#17E1BB00…FE0F9210FF18`
From a message with a known time (`time` = 2026-03-31 15:02:18 UTC):

| dpId | type | value | interpretation |
|---|---|---|---|
| 0x17 | RSSI | 187 | signal strength |
| 0x19 | WK_STATE (port1) | 0 | inactive |
| 0x1A | WK_STATE (port2) | 0 | inactive |
| 0x18 | BAT | 1 | battery |
| 0x25 | DURATION (port1) | 0 | — |
| 0x26 | DURATION (port2) | 0 | — |
| 0xFE | (T4Date) | 419369106 | **2026-03-31 17:02:18** (frame time) |

### Diivoo WT-11W (3 ports) — MQTT samples

| sample | DURATION p1/p2/p3 | WK_STATE p1/p2/p3 | EVENT_TIME (T4Date) |
|---|---|---|---|
| s1 | 600 / 0 / 0 | 33 / 0 / 0 | p1=2026-03-31 11:52:03 |
| s2 | 600 / 0 / 600 | 33 / 0 / 33 | p1=11:52:03, p3=11:59:55 |
| s3 | 0 / 0 / 600 | 0 / 0 / 33 | p3=2026-03-31 11:59:55 |
| s4 | 0 / 1680 / 600 | 0 / 33 / 33 | p2=2026-04-01 11:03:44, p3=10:45:16 |
| s5 | 600 / 15000 / 0 | 33 / 33 / 0 | p1=10:58:13, p2=14:58:35 |

EVENT_TIME = 0 always when the port is off (DURATION=0, WK_STATE=0). ✔

---

## 9. Ready-to-use decoder (Python)

```python
import datetime

CODE = {0:'CHG',1:'RAIN',2:'ALARM',3:'CHECK',8:'RM_TIME',9:'TEM',10:'RH',11:'PH',
12:'ATMOS',13:'TOTAL_RAIN',14:'V_FLOW',15:'LAST_USAGE',16:'CURRENT',17:'POWER',
18:'ENERGY',19:'DURATION',20:'WATER_TOTAL',21:'EVENT_TIME',22:'TREND',23:'SENSOR_F',
24:'V_WIND',25:'ILLUMINANCE',26:'TOTAL_TODAY',27:'TOTAL_TODAY',28:'TOTAL_TODAY',
29:'VOLTAGE',30:'WK_STATE',31:'BAT',32:'RSSI',33:'MAX_TEM',34:'MAX_RH',
35:'MAX_STATE_MOS',36:'MAX_WIND',37:'WATER_ZONES',38:'TS_DET',39:'STA_VALVE',
40:'STA_JOB',41:'STA_CALL',42:'STA_WATER_PS',43:'HOUR_RAIN',44:'DAY_RAIN',
45:'WEEK_RAIN',46:'STA_CUR_FLOW'}

def s8(x):           # sign-extend like Java's aget-byte
    return x - 256 if x >= 128 else x

def le(payload):     # little-endian unsigned int
    r = 0
    for i, v in enumerate(payload):
        r |= (v & 0xFF) << (8 * i)
    return r

def t4date(p):       # T4Date.getT4DateByParam — bit-packed date
    return "%04d-%02d-%02d %02d:%02d:%02d" % (
        ((p >> 26) & 0x3F) + 2020,   # year
        (p >> 22) & 0x0F,            # month
        (p >> 17) & 0x1F,            # day
        (p >> 12) & 0x1F,            # hour
        (p >> 6)  & 0x3F,            # minute
        p & 0x3F)                    # second

def decode(s):
    if '#' in s:                     # strip the "NN#" counter prefix
        s = s.split('#', 1)[1]
    s = s.replace(' ', '')
    b = [int(s[i*2:i*2+2], 16) for i in range(len(s)//2)]
    out, p1, n = [], 0, len(b)
    while p1 < n:
        dp_id = b[p1] & 0xFF; p1 += 1
        if p1 >= n:
            break
        flag = b[p1]; v4 = s8(flag)
        if (v4 >> 7) & 1 == 0:                       # short record
            tc = (v4 >> 4) & 7; payload = []; p1 += 1
        else:                                        # long record
            code5 = (v4 >> 2) & 0x1F; ln = v4 & 3
            if code5 <= 0x1E:
                tc = code5 + 8; total = ln + 2
                payload = b[p1+1:p1+total]; p1 += total
            else:                                    # ext
                p1 += 1; tc = (b[p1] & 0xFF) + 0x27; total = ln + 2
                payload = b[p1+1:p1+total]; p1 += total
        val = le(payload) if payload else None
        name = CODE.get(tc, '?')
        extra = t4date(val) if name == 'EVENT_TIME' and val else ''
        out.append((dp_id, tc, name, val, extra))
    return out

if __name__ == '__main__':
    blob = "11#17E1BB0019D8001AD8001BD8001D201E201F2018DC0121B70000000022B70000000023B70000000025AD000026AD000027AD0000FEFF0F9210FF18"
    for dp_id, tc, name, val, extra in decode(blob):
        print("dpId 0x%02X | %-11s | val=%s %s" % (dp_id, name, val, extra))
```

---

## 10. Source file map

| File (smali) | Role |
|---|---|
| `com/baldr/homgar/service/aliLinkkit/AliMqttService.smali` | MQTT receive, `#P…` frame, `dealMQTTMsg` |
| `com/baldr/homgar/service/aliLinkkit/AliMqttMsg.smali`, `Params.smali` | message JSON DTOs |
| `com/baldr/homgar/bean/DpDeviceStatus$Companion.smali` | TLV parser (hex → byte[] → fields) |
| `b4/B.smali` | channel type enum (`typeCode` → name) |
| `com/baldr/homgar/bean/T4Date$Companion.smali` | date unpacking (T4/D2/… variants) |
| `com/baldr/homgar/bean/DeviceStatus.smali` | dpId↔port mapping, date-variant choice |
| `com/baldr/homgar/api/http/response/RecDeviceDpModel.smali` | DP spec from API (dpPort, dpCode) |
| `com/baldr/homgar/api/http/response/RecDeviceDpSpec.smali` | DP spec from API (decimal, unit, mask) |

> To fill in `dpPort` / `decimal` / `unit` for a specific model, you need to fetch the
> `getDpList` / `/app/common/core/productModel/json` response from the HomGar cloud.
