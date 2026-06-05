import datetime

CODE = {
    0:'CHG', 1:'RAIN', 2:'ALARM', 3:'CHECK', 8:'RM_TIME', 9:'TEM', 10:'RH', 11:'PH',
    12:'ATMOS', 13:'TOTAL_RAIN', 14:'V_FLOW', 15:'LAST_USAGE', 16:'CURRENT', 17:'POWER',
    18:'ENERGY', 19:'DURATION', 20:'WATER_TOTAL', 21:'EVENT_TIME', 22:'TREND', 23:'SENSOR_F',
    24:'V_WIND', 25:'ILLUMINANCE', 26:'TOTAL_TODAY', 27:'TOTAL_TODAY', 28:'TOTAL_TODAY',
    29:'VOLTAGE', 30:'WK_STATE', 31:'BAT', 32:'RSSI', 33:'MAX_TEM', 34:'MAX_RH',
    35:'MAX_STATE_MOS', 36:'MAX_WIND', 37:'WATER_ZONES', 38:'TS_DET', 39:'STA_VALVE',
    40:'STA_JOB', 41:'STA_CALL', 42:'STA_WATER_PS', 43:'HOUR_RAIN', 44:'DAY_RAIN',
    45:'WEEK_RAIN', 46:'STA_CUR_FLOW', 54: 'T4_DATE'  # 0xFE is frame time
}

def s8(x):
    """sign-extend like Java's aget-byte"""
    return x - 256 if x >= 128 else x

def le(payload):
    """little-endian unsigned int"""
    r = 0
    for i, v in enumerate(payload):
        r |= (v & 0xFF) << (8 * i)
    return r

def t4date(p):
    """T4Date.getT4DateByParam — bit-packed date"""
    if not p:
        return None
    year = ((p >> 26) & 0x3F) + 2020
    month = (p >> 22) & 0x0F
    day = (p >> 17) & 0x1F
    hour = (p >> 12) & 0x1F
    minute = (p >> 6) & 0x3F
    second = p & 0x3F
    if month == 0 or day == 0:
        return None
    try:
        dt = datetime.datetime(year, month, day, hour, minute, second)
        return dt.timestamp()
    except ValueError:
        return None

def decode(s):
    """
    Decodes a Homgar MQTT TLV payload.
    Returns a list of dicts: [{'dp_id': int, 'type_code': int, 'name': str, 'value': int | None}]
    """
    if not s:
        return []
        
    if '#' in s:                     # strip the "NN#" counter prefix
        s = s.split('#', 1)[1]
    
    s = s.replace(' ', '')
    b = [int(s[i*2:i*2+2], 16) for i in range(len(s)//2)]
    
    out = []
    p1 = 0
    n = len(b)
    
    while p1 < n:
        dp_id = b[p1] & 0xFF
        p1 += 1
        if p1 >= n:
            break
            
        flag = b[p1]
        v4 = s8(flag)
        
        if (v4 >> 7) & 1 == 0:                       # short record
            tc = (v4 >> 4) & 7
            payload = []
            p1 += 1
        else:                                        # long record
            code5 = (v4 >> 2) & 0x1F
            ln = v4 & 3
            if code5 <= 0x1E:
                tc = code5 + 8
                total = ln + 2
                payload = b[p1+1:p1+total]
                p1 += total
            else:                                    # ext
                p1 += 1
                if p1 >= n:
                    break
                tc = (b[p1] & 0xFF) + 0x27
                total = ln + 2
                payload = b[p1+1:p1+total]
                p1 += total
                
        val = le(payload) if payload else None
        
        # Fallback for short record if value is the flag
        if not payload and (v4 >> 7) & 1 == 0:
            val = flag
            
        name = CODE.get(tc, '?')
        
        out.append({
            "dp_id": dp_id,
            "type_code": tc,
            "name": name,
            "value": val
        })
        
    return out

def get_records_by_dp_id(s):
    """Returns a dictionary mapping dp_id to its decoded record"""
    records = decode(s)
    return {r['dp_id']: r for r in records}
