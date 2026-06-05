"""
HomGar DP TLV decoder.

Decodes the hex payloads observed over MQTT/CoAP/HTTP for HomGar/Baldr
irrigation controllers (and related sensors). The format is documented in
HOMGAR_MQTT_DECODING_en.md.

Public surface:
  decode_tlv(hex_string) -> list[DecodedChannel]
  decode_t4date(value: int) -> str | None
  t4date_to_seconds(value: int) -> float | None
  CHANNEL_NAMES: dict[int, str]
  DPID_PORT_MAP: dict[int, tuple[int, str]]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# typeCode -> channel name mapping (from smali b4/B.smali)
CHANNEL_NAMES = {
    0x00: "CHG",
    0x01: "RAIN",
    0x02: "ALARM",
    0x03: "CHECK",
    0x08: "RM_TIME",
    0x09: "TEM",
    0x0A: "RH",
    0x0B: "PH",
    0x0C: "ATMOS",
    0x0D: "TOTAL_RAIN",
    0x0E: "V_FLOW",
    0x0F: "LAST_USAGE",
    0x10: "CURRENT",
    0x11: "POWER",
    0x12: "ENERGY",
    0x13: "DURATION",
    0x14: "WATER_TOTAL",
    0x15: "EVENT_TIME",
    0x16: "TREND",
    0x17: "SENSOR_F",
    0x18: "V_WIND",
    0x19: "ILLUMINANCE",
    0x1A: "TOTAL_TODAY",
    0x1B: "TOTAL_TODAY",
    0x1C: "TOTAL_TODAY",
    0x1D: "VOLTAGE",
    0x1E: "WK_STATE",
    0x1F: "BAT",
    0x20: "RSSI",
    0x21: "MAX_TEM",
    0x22: "MAX_RH",
    0x23: "MAX_STATE_MOS",
    0x24: "MAX_WIND",
    0x25: "WATER_ZONES",
    0x26: "TS_DET",
    0x27: "STA_VALVE",
    0x28: "STA_JOB",
    0x29: "STA_CALL",
    0x2A: "STA_WATER_PS",
    0x2B: "HOUR_RAIN",
    0x2C: "DAY_RAIN",
    0x2D: "WEEK_RAIN",
    0x2E: "STA_CUR_FLOW",
}

# Extended typeCode 0x36 = 54 = frame timestamp (dpId 0xFE)
TYPECODE_FRAME_TIME = 0x36

# dpId for the frame timestamp
DPID_FRAME_TIME = 0xFE


def _le(payload: bytes) -> int:
    """Little-endian unsigned decode of arbitrary-length bytes."""
    result = 0
    for i, v in enumerate(payload):
        result |= (v & 0xFF) << (8 * i)
    return result


def decode_t4date(value: int) -> Optional[str]:
    """
    Decode T4Date packed timestamp from a 32-bit unsigned integer.

    Layout (bit ranges):
      second : bits 0-5
      minute : bits 6-11
      hour   : bits 12-16
      day    : bits 17-21
      month  : bits 22-25
      year   : bits 26-31 (base 2020)

    Returns ``YYYY-MM-DD HH:MM:SS`` or ``None`` when value is falsy.
    """
    if not value or value <= 0:
        return None

    second = value & 0x3F
    minute = (value >> 6) & 0x3F
    hour = (value >> 12) & 0x1F
    day = (value >> 17) & 0x1F
    month = (value >> 22) & 0x0F
    year = ((value >> 26) & 0x3F) + 2020

    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def t4date_to_seconds(value: int) -> Optional[float]:
    """
    Convert a T4Date value to epoch seconds.

    The T4Date fields are device-local time, but since we only ever subtract
    two T4Date values from the *same device*, timezone cancels out.
    Returns ``None`` for falsy/unparseable values.
    """
    if not value or value <= 0:
        return None

    second = value & 0x3F
    minute = (value >> 6) & 0x3F
    hour = (value >> 12) & 0x1F
    day = (value >> 17) & 0x1F
    month = (value >> 22) & 0x0F
    year = ((value >> 26) & 0x3F) + 2020

    try:
        return datetime(year, month, day, hour, minute, second).timestamp()
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class DecodedChannel:
    """Single decoded TLV record from a HomGar status payload."""

    dp_id: int
    type_code: int
    channel_name: str
    value: int
    event_time: Optional[str] = None


def _parse_hex_payload(hex_str: str) -> List[DecodedChannel]:
    """
    Parse a raw hex substring (no ``NN#`` prefix) into TLV records.

    Each record is ``[dpId] [flag_byte] [value_bytes...]``:
    * Short record  (flag bit7 == 0):
        typeCode = (flag >> 4) & 0x7, no extra payload bytes
    * Long record   (flag bit7 == 1):
        typeLen = (flag & 0x3) + 1
        code5  = (flag >> 2) & 0x1F
        if code5 <= 0x1E: typeCode = code5 + 8, payload = typeLen bytes
        if code5 == 0x1F:  extension byte, typeCode = ext + 0x27, payload = typeLen bytes
    Multi-byte values use little-endian byte order.
    """
    cleaned = hex_str.replace(" ", "")
    n = len(cleaned) // 2
    data = bytes(int(cleaned[i * 2: i * 2 + 2], 16) for i in range(n))

    results: List[DecodedChannel] = []
    pos = 0

    while pos < len(data):
        dp_id = data[pos]
        pos += 1
        if pos >= len(data):
            break

        flag = data[pos]
        flag_u = flag & 0xFF

        if (flag_u >> 7) & 0x01 == 0:
            # Short record: value packed into the flag byte itself.
            type_code = (flag_u >> 4) & 0x07
            value = flag_u
            pos += 1
        else:
            # Long record
            type_len = (flag_u & 0x03) + 1
            code5 = (flag_u >> 2) & 0x1F

            if code5 <= 0x1E:
                type_code = code5 + 8
                payload_start = pos + 1
            else:
                # Extension: next byte encodes typeCode
                if pos + 1 >= len(data):
                    break
                ext = data[pos + 1] & 0xFF
                type_code = ext + 0x27
                payload_start = pos + 2

            payload_end = payload_start + type_len
            payload = data[payload_start:payload_end]
            value = _le(payload)
            pos = payload_end

        channel_name = CHANNEL_NAMES.get(type_code, f"ext_{type_code:#x}")
        event_time = decode_t4date(value) if type_code == 0x15 else None
        results.append(DecodedChannel(
            dp_id=dp_id,
            type_code=type_code,
            channel_name=channel_name,
            value=value,
            event_time=event_time,
        ))

    return results


def decode_tlv(raw_payload: str) -> List[DecodedChannel]:
    """
    Decode a complete HomGar DP payload.

    Accepts either:
      * ``NN#<hex>``  — the counter prefix is stripped automatically
      * ``<hex>``     — raw hex string

    Returns a list of decoded channel records.
    """
    if not raw_payload:
        return []

    if "#" in raw_payload:
        raw_payload = raw_payload.split("#", 1)[1]

    raw_payload = raw_payload.strip()
    if not raw_payload:
        return []

    return _parse_hex_payload(raw_payload)


# --- dpId-to-port mapping (from HOMGAR_MQTT_DECODING_en.md §6) ---

# Maps dpId -> (physical_port_number, channel_function)
# Confirmed for 1-4 port irrigation controllers.
# Higher ports extend the same pattern (e.g. 0x1C = WK_STATE port 4).
DPID_PORT_MAP: dict[int, tuple[int, str]] = {
    # WK_STATE per port
    0x19: (1, "WK_STATE"),
    0x1A: (2, "WK_STATE"),
    0x1B: (3, "WK_STATE"),
    0x1C: (4, "WK_STATE"),
    # DURATION per port
    0x25: (1, "DURATION"),
    0x26: (2, "DURATION"),
    0x27: (3, "DURATION"),
    0x28: (4, "DURATION"),
    # EVENT_TIME per port
    0x21: (1, "EVENT_TIME"),
    0x22: (2, "EVENT_TIME"),
    0x23: (3, "EVENT_TIME"),
    0x24: (4, "EVENT_TIME"),
    # ALARM per port
    0x1D: (1, "ALARM"),
    0x1E: (2, "ALARM"),
    0x1F: (3, "ALARM"),
    0x20: (4, "ALARM"),
}


def get_channel_port(dp_id: int) -> Optional[int]:
    """Return the physical port number for a dpId, or None if unmapped."""
    entry = DPID_PORT_MAP.get(dp_id)
    return entry[0] if entry else None


def get_channel_type(dp_id: int) -> Optional[str]:
    """Return the channel function name for a dpId, or None if unmapped."""
    entry = DPID_PORT_MAP.get(dp_id)
    return entry[1] if entry else None
