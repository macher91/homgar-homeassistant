import unittest
import sys
import os
from datetime import datetime

# Ensure the module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../custom_components/homgar')))

from tlv import decode, t4date, get_records_by_dp_id

class TestTlvDecoder(unittest.TestCase):

    def test_payload_sample_1(self):
        payload = "17E1BA0019D8211 AD8001 BD8001 D201E2 01F2018DC01 21B703BDFE18 22B700000000 23B700000000 25AD580226 AD000027AD0000 FEFF0F1DBCFE18"
        records = get_records_by_dp_id(payload)
        
        # Port 1
        self.assertEqual(records[0x19]['value'], 33) # WK_STATE port 1
        self.assertEqual(records[0x19]['value'] & 1, 1) # Interpreted as ON
        
        self.assertEqual(records[0x25]['value'], 600) # DURATION port 1
        
        val_event = records[0x21]['value']
        self.assertEqual(val_event, 419347715) # EVENT_TIME port 1
        self.assertEqual(datetime.fromtimestamp(t4date(val_event)).strftime('%Y-%m-%d %H:%M:%S'), '2026-03-31 11:52:03')
        
        # Port 2
        self.assertEqual(records[0x1A]['value'], 0) # WK_STATE port 2
        self.assertEqual(records[0x1A]['value'] & 1, 0) # Interpreted as OFF
        
        self.assertEqual(records[0x26]['value'], 0) # DURATION port 2
        
        # Frame Time
        val_frame = records[0xFE]['value']
        self.assertEqual(val_frame, 419347485)
        self.assertEqual(datetime.fromtimestamp(t4date(val_frame)).strftime('%Y-%m-%d %H:%M:%S'), '2026-03-31 11:48:29')

    def test_payload_sample_2(self):
        payload = "17E1BA0019D8211 AD8001 BD8211 D201E2 01F2018DC01 21B703BDFE18 22B700000000 23B7F7BEFE18 25AD580226 AD000027AD5802 FEFF0F76BCFE18"
        records = get_records_by_dp_id(payload)
        
        # Port 1
        self.assertEqual(records[0x19]['value'], 33) # WK_STATE
        self.assertEqual(records[0x19]['value'] & 1, 1) # Interpreted as ON
        self.assertEqual(records[0x25]['value'], 600) # DURATION
        
        # Port 3
        self.assertEqual(records[0x1B]['value'], 33) # WK_STATE
        self.assertEqual(records[0x1B]['value'] & 1, 1) # Interpreted as ON
        self.assertEqual(records[0x27]['value'], 600) # DURATION
        
        val_event = records[0x23]['value']
        self.assertEqual(val_event, 419348215) # EVENT_TIME
        self.assertEqual(datetime.fromtimestamp(t4date(val_event)).strftime('%Y-%m-%d %H:%M:%S'), '2026-03-31 11:59:55')

        val_frame = records[0xFE]['value']
        self.assertEqual(datetime.fromtimestamp(t4date(val_frame)).strftime('%Y-%m-%d %H:%M:%S'), '2026-03-31 11:49:54')

    def test_payload_sample_5(self):
        payload = "17E1BC0019D8001 AD8211 BD8211 D201E2 01F2018DC01 21B700000000 22B7ECB00219 23B750AB0219 25AD000026 AD900627AD5802 FEFF0FF0A80219"
        records = get_records_by_dp_id(payload)
        
        # Port 2
        self.assertEqual(records[0x1A]['value'], 33) # WK_STATE
        self.assertEqual(records[0x1A]['value'] & 1, 1) # Interpreted as ON
        self.assertEqual(records[0x26]['value'], 1680) # DURATION
        
        val_event2 = records[0x22]['value']
        self.assertEqual(val_event2, 419606764) # EVENT_TIME
        self.assertEqual(datetime.fromtimestamp(t4date(val_event2)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 11:03:44')
        
        # Port 3
        self.assertEqual(records[0x1B]['value'], 33) # WK_STATE
        self.assertEqual(records[0x1B]['value'] & 1, 1) # Interpreted as ON
        self.assertEqual(records[0x27]['value'], 600) # DURATION
        
        val_event3 = records[0x23]['value']
        self.assertEqual(val_event3, 419605328) # EVENT_TIME
        self.assertEqual(datetime.fromtimestamp(t4date(val_event3)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 10:45:16')

        val_frame = records[0xFE]['value']
        self.assertEqual(datetime.fromtimestamp(t4date(val_frame)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 10:35:48')

    def test_payload_sample_6(self):
        payload = "17E1BA0019D8211 AD8211 BD8001 D201E2 01F2018DC01 21B78DAE0219 22B7A3EE0219 23B700000000 25AD580226 AD983A27AD0000 FEFF0F27AC0219"
        records = get_records_by_dp_id(payload)
        
        # Port 1
        self.assertEqual(records[0x19]['value'], 33) # WK_STATE
        self.assertEqual(records[0x19]['value'] & 1, 1) # ON
        self.assertEqual(records[0x25]['value'], 600) # DURATION
        
        val_event1 = records[0x21]['value']
        self.assertEqual(datetime.fromtimestamp(t4date(val_event1)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 10:58:13')
        
        # Port 2
        self.assertEqual(records[0x1A]['value'], 33) # WK_STATE
        self.assertEqual(records[0x1A]['value'] & 1, 1) # ON
        self.assertEqual(records[0x26]['value'], 15000) # DURATION
        
        val_event2 = records[0x22]['value']
        self.assertEqual(datetime.fromtimestamp(t4date(val_event2)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 14:58:35')
        
        # Port 3
        self.assertEqual(records[0x1B]['value'], 0) # WK_STATE
        self.assertEqual(records[0x1B]['value'] & 1, 0) # OFF
        
        val_event3 = records[0x23]['value']
        self.assertEqual(val_event3, 0)
        self.assertIsNone(t4date(val_event3)) # 0 (Inactive)

        val_frame = records[0xFE]['value']
        self.assertEqual(datetime.fromtimestamp(t4date(val_frame)).strftime('%Y-%m-%d %H:%M:%S'), '2026-04-01 10:48:39')

if __name__ == '__main__':
    unittest.main()
