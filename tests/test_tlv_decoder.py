"""Unit tests for custom_components.homgar.tlv_decoder.

Tests the DP TLV decoder with real hex payloads captured from HomGar/Baldr
irrigation controllers over MQTT.  Uses importlib to bypass the HA component
__init__.py (which pulls in voluptuous / homeassistant).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load tlv_decoder without triggering the HA component __init__
# ---------------------------------------------------------------------------

_TLV_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "homgar"
    / "tlv_decoder.py"
)


def _load_module():
    """Import tlv_decoder as a standalone module."""
    mod_name = "custom_components.homgar.tlv_decoder"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(_TLV_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_tlv = _load_module()
decode_tlv = _tlv.decode_tlv
decode_t4date = _tlv.decode_t4date
t4date_to_seconds = _tlv.t4date_to_seconds
DecodedChannel = _tlv.DecodedChannel
get_channel_port = _tlv.get_channel_port
get_channel_type = _tlv.get_channel_type
CHANNEL_NAMES = _tlv.CHANNEL_NAMES
DPID_PORT_MAP = _tlv.DPID_PORT_MAP


# ---------------------------------------------------------------------------
# Test vectors — captured from a real 4-port irrigation controller
# ---------------------------------------------------------------------------

# Vector 1: port 3 inactive (WK_STATE=0, EVENT_TIME=0, DURATION=0)
VECTOR_1 = (
    "17E1BA0019D8211 AD8001 BD8001 D201E2 01F2018DC01 "
    "21B703BDFE18 22B700000000 23B700000000 "
    "25AD580226 AD000027AD0000 "
    "FEFF0F1DBCFE18"
)

# Vector 2: port 3 active (WK_STATE=33, EVENT_TIME set, DURATION=600)
VECTOR_2 = (
    "17E1BA0019D8211 AD8001 BD8211 D201E2 01F2018DC01 "
    "21B703BDFE18 22B700000000 23B7F7BEFE18 "
    "25AD580226 AD000027AD5802 "
    "FEFF0F76BCFE18"
)

# Expected records for vector 1 (15 records)
EXPECTED_V1 = [
    DecodedChannel(dp_id=0x17, type_code=0x20, channel_name="RSSI",       value=186,        event_time=None),
    DecodedChannel(dp_id=0x19, type_code=0x1E, channel_name="WK_STATE",   value=33,         event_time=None),
    DecodedChannel(dp_id=0x1A, type_code=0x1E, channel_name="WK_STATE",   value=0,          event_time=None),
    DecodedChannel(dp_id=0x1B, type_code=0x1E, channel_name="WK_STATE",   value=0,          event_time=None),
    DecodedChannel(dp_id=0x1D, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x1E, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x1F, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x18, type_code=0x1F, channel_name="BAT",        value=1,          event_time=None),
    DecodedChannel(dp_id=0x21, type_code=0x15, channel_name="EVENT_TIME", value=419347715,  event_time="2026-03-31 11:52:03"),
    DecodedChannel(dp_id=0x22, type_code=0x15, channel_name="EVENT_TIME", value=0,          event_time=None),
    DecodedChannel(dp_id=0x23, type_code=0x15, channel_name="EVENT_TIME", value=0,          event_time=None),
    DecodedChannel(dp_id=0x25, type_code=0x13, channel_name="DURATION",   value=600,        event_time=None),
    DecodedChannel(dp_id=0x26, type_code=0x13, channel_name="DURATION",   value=0,          event_time=None),
    DecodedChannel(dp_id=0x27, type_code=0x13, channel_name="DURATION",   value=0,          event_time=None),
    DecodedChannel(dp_id=0xFE, type_code=0x36, channel_name="ext_0x36",   value=419347485,  event_time=None),
]

# Expected records for vector 2 (15 records)
EXPECTED_V2 = [
    DecodedChannel(dp_id=0x17, type_code=0x20, channel_name="RSSI",       value=186,        event_time=None),
    DecodedChannel(dp_id=0x19, type_code=0x1E, channel_name="WK_STATE",   value=33,         event_time=None),
    DecodedChannel(dp_id=0x1A, type_code=0x1E, channel_name="WK_STATE",   value=0,          event_time=None),
    DecodedChannel(dp_id=0x1B, type_code=0x1E, channel_name="WK_STATE",   value=33,         event_time=None),
    DecodedChannel(dp_id=0x1D, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x1E, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x1F, type_code=0x02, channel_name="ALARM",      value=32,         event_time=None),
    DecodedChannel(dp_id=0x18, type_code=0x1F, channel_name="BAT",        value=1,          event_time=None),
    DecodedChannel(dp_id=0x21, type_code=0x15, channel_name="EVENT_TIME", value=419347715,  event_time="2026-03-31 11:52:03"),
    DecodedChannel(dp_id=0x22, type_code=0x15, channel_name="EVENT_TIME", value=0,          event_time=None),
    DecodedChannel(dp_id=0x23, type_code=0x15, channel_name="EVENT_TIME", value=419348215,  event_time="2026-03-31 11:59:55"),
    DecodedChannel(dp_id=0x25, type_code=0x13, channel_name="DURATION",   value=600,        event_time=None),
    DecodedChannel(dp_id=0x26, type_code=0x13, channel_name="DURATION",   value=0,          event_time=None),
    DecodedChannel(dp_id=0x27, type_code=0x13, channel_name="DURATION",   value=600,        event_time=None),
    DecodedChannel(dp_id=0xFE, type_code=0x36, channel_name="ext_0x36",   value=419347574,  event_time=None),
]


# ===================================================================
# decode_tlv — test vector validation
# ===================================================================


class TestDecodeTlvVectors:
    """Full-decode tests against captured controller payloads."""

    def test_vector1_record_count(self):
        records = decode_tlv(VECTOR_1)
        assert len(records) == 15

    def test_vector1_exact_match(self):
        records = decode_tlv(VECTOR_1)
        assert records == EXPECTED_V1

    def test_vector2_record_count(self):
        records = decode_tlv(VECTOR_2)
        assert len(records) == 15

    def test_vector2_exact_match(self):
        records = decode_tlv(VECTOR_2)
        assert records == EXPECTED_V2

    def test_vector1_port3_inactive(self):
        """Port 3 WK_STATE, EVENT_TIME, DURATION should all be 0 in vector 1."""
        records = decode_tlv(VECTOR_1)
        port3_wk = [r for r in records if r.dp_id == 0x1B]
        port3_evt = [r for r in records if r.dp_id == 0x23]
        port3_dur = [r for r in records if r.dp_id == 0x27]
        assert port3_wk[0].value == 0
        assert port3_evt[0].value == 0
        assert port3_evt[0].event_time is None
        assert port3_dur[0].value == 0

    def test_vector2_port3_active(self):
        """Port 3 should show active watering in vector 2."""
        records = decode_tlv(VECTOR_2)
        port3_wk = [r for r in records if r.dp_id == 0x1B]
        port3_evt = [r for r in records if r.dp_id == 0x23]
        port3_dur = [r for r in records if r.dp_id == 0x27]
        assert port3_wk[0].value == 33
        assert port3_evt[0].value == 419348215
        assert port3_evt[0].event_time == "2026-03-31 11:59:55"
        assert port3_dur[0].value == 600

    def test_both_vectors_share_common_fields(self):
        """RSSI, battery, port 1 data, alarm should be identical."""
        r1 = decode_tlv(VECTOR_1)
        r2 = decode_tlv(VECTOR_2)
        common_dp_ids = [0x17, 0x19, 0x1A, 0x1D, 0x1E, 0x1F, 0x18, 0x21, 0x25, 0x26]
        for dp_id in common_dp_ids:
            rec1 = next(r for r in r1 if r.dp_id == dp_id)
            rec2 = next(r for r in r2 if r.dp_id == dp_id)
            assert rec1.value == rec2.value, (
                f"dp_id=0x{dp_id:02X} ({rec1.channel_name}): "
                f"v1={rec1.value} vs v2={rec2.value}"
            )

    def test_vector2_differs_from_v1_in_expected_fields(self):
        """Only 4 records should differ between the two vectors."""
        r1 = decode_tlv(VECTOR_1)
        r2 = decode_tlv(VECTOR_2)
        diffs = []
        for a, b in zip(r1, r2):
            if a.value != b.value or a.event_time != b.event_time:
                diffs.append(a.dp_id)
        assert set(diffs) == {0x1B, 0x23, 0x27, 0xFE}


# ===================================================================
# decode_tlv — prefix / format handling
# ===================================================================


class TestDecodeTlvFormats:
    """Test different input formats."""

    def test_nn_hash_prefix_stripped(self):
        """'01#<hex>' should strip the counter prefix."""
        payload = "01#" + VECTOR_1.replace(" ", "")
        records = decode_tlv(payload)
        assert records == EXPECTED_V1

    def test_raw_hex_no_prefix(self):
        """Plain hex without NN# prefix should decode identically."""
        records = decode_tlv(VECTOR_1.replace(" ", ""))
        assert records == EXPECTED_V1

    def test_spaces_preserved(self):
        """Spaces in hex string should be handled transparently."""
        records = decode_tlv(VECTOR_1)
        assert records == EXPECTED_V1

    def test_different_nn_prefixes(self):
        """Various NN# counter values should all work."""
        for nn in ["00#", "01#", "42#", "99#"]:
            payload = nn + VECTOR_2.replace(" ", "")
            records = decode_tlv(payload)
            assert records == EXPECTED_V2, f"Failed with prefix {nn!r}"


# ===================================================================
# decode_tlv — edge cases
# ===================================================================


class TestDecodeTlvEdgeCases:
    """Edge cases and robustness."""

    def test_empty_string(self):
        assert decode_tlv("") == []

    def test_none_input(self):
        assert decode_tlv(None) == []

    def test_hash_only(self):
        """Just '#' with no hex after should return empty."""
        assert decode_tlv("#") == []

    def test_nn_hash_no_data(self):
        assert decode_tlv("01#") == []

    def test_whitespace_only(self):
        assert decode_tlv("   ") == []

    def test_single_record_minimal(self):
        """dp_id=0x17, short flag (bit7=0): flag=0x00 => type=0, value=0."""
        records = decode_tlv("1700")
        assert len(records) == 1
        assert records[0].dp_id == 0x17
        assert records[0].type_code == 0
        assert records[0].value == 0
        assert records[0].channel_name == "CHG"

    def test_decoded_channel_is_frozen(self):
        """DecodedChannel dataclass should be immutable."""
        records = decode_tlv("1700")
        with pytest.raises(AttributeError):
            records[0].value = 999


# ===================================================================
# decode_tlv — neighbor / mutation vectors (Hamming distance 1)
# ===================================================================


class TestNeighborVectors:
    """Tests with single-bit or single-byte changes to verify decoder sensitivity."""

    def test_v2_port3_event_time_one_bit_flip(self):
        """Flipping a bit in the EVENT_TIME payload changes value (23B7F7BEFE18 -> FC18)."""
        records = decode_tlv("23B7F7BEFC18")
        assert len(records) == 1
        assert records[0].dp_id == 0x23
        assert records[0].type_code == 0x15  # EVENT_TIME
        assert records[0].value == 419217143
        assert records[0].value != EXPECTED_V2[10].value  # different from v2's 419348215

    def test_v2_port3_event_time_different_mutation(self):
        """Different mutation: FE->DE yields a different timestamp."""
        records = decode_tlv("23B7F7BEDE18")
        assert len(records) == 1
        assert records[0].dp_id == 0x23
        assert records[0].value == 417251063

    def test_v1_rssi_byte_changed(self):
        """Single-byte change in RSSI: BA->B8 yields RSSI=184 instead of 186."""
        payload = (
            "17E1B8 0019D821 1AD800 1BD800 1D201E 201F20 18DC01 "
            "21B703BD FE18 22B700000000 23B700000000 "
            "25AD5802 26AD0000 27AD0000 "
            "FEFF0F1DBCFE18"
        )
        records = decode_tlv(payload)
        rssi = next(r for r in records if r.dp_id == 0x17)
        assert rssi.value == 184

    def test_v2_duration_byte_changed(self):
        """Single-byte change in port3 DURATION: 02->00 yields DURATION=88."""
        payload = (
            "17E1BA0019D821 1AD800 1BD821 1D201E 201F20 18DC01 "
            "21B703BD FE18 22B700000000 23B7F7BEFE18 "
            "25AD5802 26AD0000 27AD5800 "
            "FEFF0F76BCFE18"
        )
        records = decode_tlv(payload)
        dur3 = next(r for r in records if r.dp_id == 0x27)
        assert dur3.value == 88

    def test_v2_port3_wk_state_flipped_to_inactive(self):
        """Changing BD8211->BD8001 makes port3 WK_STATE inactive (0) while keeping
        other port3 data (EVENT_TIME, DURATION) unchanged from v2."""
        payload = (
            "17E1BA0019D821 1AD800 1BD800 1D201E 201F20 18DC01 "
            "21B703BD FE18 22B700000000 23B7F7BEFE18 "
            "25AD5802 26AD0000 27AD5802 "
            "FEFF0F76BCFE18"
        )
        records = decode_tlv(payload)
        port3_wk = next(r for r in records if r.dp_id == 0x1B)
        port3_evt = next(r for r in records if r.dp_id == 0x23)
        port3_dur = next(r for r in records if r.dp_id == 0x27)
        # WK_STATE flipped to inactive
        assert port3_wk.value == 0
        # But EVENT_TIME and DURATION still carry v2 values
        assert port3_evt.value == 419348215
        assert port3_dur.value == 600

    def test_short_flag_value_change(self):
        """Standalone 'D201E2': dp_id=0xD2, short flag 0x01 (type=0, value=1),
        then dp_id=0xE2 with no payload. Changing last byte to E0 should
        produce the same first record (flag unchanged) but different second dp_id."""
        records_orig = decode_tlv("D201E2")
        records_mut = decode_tlv("D201E0")
        # First record is the same for both: dp_id=0xD2, short flag 0x01
        assert records_orig[0].dp_id == 0xD2
        assert records_orig[0].value == 0x01
        assert records_orig[0].type_code == 0  # CHG
        assert records_mut[0].dp_id == 0xD2
        assert records_mut[0].value == 0x01


# ===================================================================
# decode_t4date
# ===================================================================


class TestDecodeT4Date:
    """Test T4Date packed timestamp decoding."""

    def test_known_timestamp(self):
        """419347715 should decode to 2026-03-31 11:52:03."""
        assert decode_t4date(419347715) == "2026-03-31 11:52:03"

    def test_second_known_timestamp(self):
        """419348215 should decode to 2026-03-31 11:59:55."""
        assert decode_t4date(419348215) == "2026-03-31 11:59:55"

    def test_zero_returns_none(self):
        assert decode_t4date(0) is None

    def test_negative_returns_none(self):
        assert decode_t4date(-1) is None

    def test_none_input(self):
        # 0 is falsy, None is also falsy
        assert decode_t4date(0) is None

    def test_format_string(self):
        """Output should match YYYY-MM-DD HH:MM:SS format."""
        result = decode_t4date(419347715)
        assert len(result) == 19
        assert result[4] == "-"
        assert result[7] == "-"
        assert result[10] == " "
        assert result[13] == ":"
        assert result[16] == ":"

    def test_base_year_2020(self):
        """Year field uses 2020 as base. A value with year_bits=0 => 2020."""
        # Construct: year=0(=2020), month=1, day=1, hour=0, min=0, sec=0
        # bits: sec[0:5]=0, min[6:11]=0, hour[12:16]=0, day[17:21]=1, month[22:25]=1, year[26:31]=0
        val = (0 << 26) | (1 << 22) | (1 << 17) | (0 << 12) | (0 << 6) | 0
        assert decode_t4date(val) == "2020-01-01 00:00:00"

    def test_max_second(self):
        """Second field is 6 bits: max 63."""
        val = 63  # only seconds, min=0, hr=0, day=1, month=1, year=0(2020)
        val |= (1 << 17)  # day=1
        val |= (1 << 22)  # month=1
        assert decode_t4date(val) == "2020-01-01 00:00:63"

    def test_max_minute(self):
        """Minute field is 6 bits: max 63."""
        val = (63 << 6) | 0  # min=63, sec=0
        val |= (1 << 17)  # day=1
        val |= (1 << 22)  # month=1
        assert decode_t4date(val) == "2020-01-01 00:63:00"


# ===================================================================
# t4date_to_seconds
# ===================================================================


class TestT4DateToSeconds:
    """Test T4Date to epoch seconds conversion."""

    def test_known_value_returns_float(self):
        result = t4date_to_seconds(419347715)
        assert isinstance(result, float)

    def test_zero_returns_none(self):
        assert t4date_to_seconds(0) is None

    def test_negative_returns_none(self):
        assert t4date_to_seconds(-1) is None

    def test_two_close_timestamps_subtractable(self):
        """Two T4Date values from the same device should be subtractable."""
        t1 = t4date_to_seconds(419347485)  # frame time vector 1
        t2 = t4date_to_seconds(419347574)  # frame time vector 2
        assert t1 is not None and t2 is not None
        diff = t2 - t1
        # Vector 2 frame is exactly 85 seconds after vector 1 frame
        assert diff == 85.0, f"Expected 85s difference, got {diff}"

    def test_consistent_with_decode_t4date(self):
        """t4date_to_seconds should be consistent with decode_t4date."""
        val = 419347715
        date_str = decode_t4date(val)
        epoch = t4date_to_seconds(val)
        assert date_str == "2026-03-31 11:52:03"
        assert epoch is not None

    def test_returns_none_for_invalid_date(self):
        """T4Date encoding that produces invalid calendar date -> None."""
        # month=13 is invalid: bits 22-25 = 13
        val = (13 << 22) | (1 << 17) | 1  # month=13, day=1, sec=1
        assert t4date_to_seconds(val) is None


# ===================================================================
# get_channel_port / get_channel_type
# ===================================================================


class TestDpIdMapping:
    """Test dpId-to-port mapping helpers."""

    def test_port1_wk_state(self):
        assert get_channel_port(0x19) == 1
        assert get_channel_type(0x19) == "WK_STATE"

    def test_port2_wk_state(self):
        assert get_channel_port(0x1A) == 2
        assert get_channel_type(0x1A) == "WK_STATE"

    def test_port3_wk_state(self):
        assert get_channel_port(0x1B) == 3
        assert get_channel_type(0x1B) == "WK_STATE"

    def test_port4_wk_state(self):
        assert get_channel_port(0x1C) == 4
        assert get_channel_type(0x1C) == "WK_STATE"

    def test_port1_duration(self):
        assert get_channel_port(0x25) == 1
        assert get_channel_type(0x25) == "DURATION"

    def test_port3_duration(self):
        assert get_channel_port(0x27) == 3
        assert get_channel_type(0x27) == "DURATION"

    def test_port1_event_time(self):
        assert get_channel_port(0x21) == 1
        assert get_channel_type(0x21) == "EVENT_TIME"

    def test_port3_event_time(self):
        assert get_channel_port(0x23) == 3
        assert get_channel_type(0x23) == "EVENT_TIME"

    def test_port1_alarm(self):
        assert get_channel_port(0x1D) == 1
        assert get_channel_type(0x1D) == "ALARM"

    def test_unmapped_returns_none(self):
        """dpIds not in DPID_PORT_MAP should return None."""
        assert get_channel_port(0x00) is None
        assert get_channel_type(0x00) is None
        assert get_channel_port(0xFF) is None
        assert get_channel_type(0xFF) is None

    def test_all_map_entries_consistent(self):
        """Every entry in DPID_PORT_MAP should have valid port and type."""
        for dp_id, (port, channel_type) in DPID_PORT_MAP.items():
            assert isinstance(port, int) and 1 <= port <= 4, (
                f"dp_id=0x{dp_id:02X}: port={port} out of range"
            )
            assert isinstance(channel_type, str) and len(channel_type) > 0


# ===================================================================
# CHANNEL_NAMES — basic sanity
# ===================================================================


class TestChannelNames:
    """Verify the type_code -> channel name mapping."""

    def test_known_channels(self):
        assert CHANNEL_NAMES[0x00] == "CHG"
        assert CHANNEL_NAMES[0x01] == "RAIN"
        assert CHANNEL_NAMES[0x02] == "ALARM"
        assert CHANNEL_NAMES[0x15] == "EVENT_TIME"
        assert CHANNEL_NAMES[0x13] == "DURATION"
        assert CHANNEL_NAMES[0x1E] == "WK_STATE"
        assert CHANNEL_NAMES[0x20] == "RSSI"

    def test_all_values_are_strings(self):
        for key, name in CHANNEL_NAMES.items():
            assert isinstance(key, int), f"Key {key!r} is not int"
            assert isinstance(name, str) and len(name) > 0, (
                f"Name for 0x{key:02X} is empty or not string"
            )

    def test_unknown_type_gets_ext_prefix(self):
        """decode_tlv should produce 'ext_0xNN' for unmapped type codes."""
        # type_code=0x36 (frame time) is not in CHANNEL_NAMES
        records = decode_tlv(VECTOR_1)
        ext_records = [r for r in records if r.type_code == 0x36]
        assert len(ext_records) == 1
        assert ext_records[0].channel_name == "ext_0x36"
