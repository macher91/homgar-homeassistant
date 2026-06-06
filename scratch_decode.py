import sys
sys.path.append('custom_components/homgar')
from tlv import decode, t4date

import datetime

payloads = [
    "17E1BA0019D8211 AD8001 BD8001 D201E2 01F2018DC01 21B703BDFE18 22B700000000 23B700000000 25AD580226 AD000027AD0000 FEFF0F1DBCFE18",
    "17E1BA0019D8211 AD8001 BD8211 D201E2 01F2018DC01 21B703BDFE18 22B700000000 23B7F7BEFE18 25AD580226 AD000027AD5802 FEFF0F76BCFE18",
    "17E1BA0019D8211 AD8001 BD8211 D201E2 01F2018DC01 21B703BDFE18 22B700000000 23B7F7BEFE18 25AD580226 AD000027AD5802 FEFF0F76BCFE18",
    "17E1BC0019D8001 AD8001 BD8211 D201E2 01F2018DC01 21B700000000 22B700000000 23B7F7BEFE18 25AD000026 AD000027AD5802 FEFF0F04BDFE18",
    "17E1BC0019D8001 AD8211 BD8211 D201E2 01F2018DC01 21B700000000 22B7ECB00219 23B750AB0219 25AD000026 AD900627AD5802 FEFF0FF0A80219",
    "17E1BA0019D8211 AD8211 BD8001 D201E2 01F2018DC01 21B78DAE0219 22B7A3EE0219 23B700000000 25AD580226 AD983A27AD0000 FEFF0F27AC0219"
]

print("| Payload | dpId | Name | Value | Interpreted |")
print("|---|---|---|---|---|")

for idx, p in enumerate(payloads):
    records = decode(p)
    print(f"| **Sample {idx+1}** | | | | |")
    for r in records:
        val = r['value']
        interp = ""
        if r['name'] == 'EVENT_TIME' or r['name'] == 'T4_DATE':
            ts = t4date(val)
            if ts:
                interp = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            else:
                interp = "0 (Inactive)"
        elif r['name'] == 'DURATION':
            interp = f"{val} sec"
        elif r['name'] == 'WK_STATE':
            interp = "ON" if val & 1 else ("OFF" if val == 0 else "OFF (Idle)")
        elif r['name'] in ['RSSI', 'BAT']:
            interp = str(val)
        
        print(f"| | `0x{r['dp_id']:02X}` | {r['name']} | {val} | {interp} |")

