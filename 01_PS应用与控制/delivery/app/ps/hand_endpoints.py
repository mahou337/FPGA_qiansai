"""User-confirmed individual endpoints, raw values are authoritative.
Bit evidence: gesture_classifier._states: matched tip=1,
calibrated retracted sector=0. Not inferred from demo OpenHand/CloseHand names.
"""
import math
IDS = tuple(range(1, 9))
PAIRS = ((7, 8), (1, 2), (3, 4), (5, 6))
OPEN = dict(zip(IDS, (584,404,418,602,439,576,508,514)))
CLOSED = dict(zip(IDS, (206,769,90,989,128,895,195,864)))  # Snapshot + authorized thumb +/-68raw; ACTIVE_ENDPOINTS.json
LIMITS = {i: tuple(sorted((OPEN[i], CLOSED[i]))) for i in IDS}
FEEDBACK_MARGIN_RAW = 15  # User-authorized feedback envelope; targets remain exact endpoints.
SPEED_RADIANS = 5.0  # User-requested MaxSpeed=5, radians/second parameter.
LOAD_HARD_LIMIT_RAW = 800  # Immediate fault at/above this feedback value.
LOAD_WARN_RAW = 750  # Active-motion transient band; never allowed at ARM.
LOAD_WARN_SECONDS = .10  # Bounded diagnostic trial, not manufacturer rating.
VOLTAGE_WINDOW = (4.5, 7.6)  # Inclusive user-requested software feedback window.


def check_raw(sid, value, feedback=False):
    if sid not in IDS or type(value) is not int:
        raise ValueError('Invalid servo/raw type')
    lo, hi = LIMITS[sid]
    margin = FEEDBACK_MARGIN_RAW if feedback else 0
    if not max(0,lo-margin) <= value <= min(1023,hi+margin):
        raise RuntimeError('Servo {} raw {} outside {}..{} margin={}'.format(sid,value,lo,hi,margin))
    return value


def targets(code):
    if not isinstance(code,str) or len(code)!=4 or set(code)-set('01'):
        raise ValueError('Four binary bits required')
    return {sid:(OPEN if bit=='1' else CLOSED)[sid]
            for bit,pair in zip(code,PAIRS) for sid in pair}


def health(values):
    for sid,v in values.items():
        check_raw(sid,v['raw'],feedback=True)
        angle=300.0*(v['raw']-511)/1024
        if not math.isfinite(v['angle']) or abs(v['angle']-angle)>.001:
            raise RuntimeError('Inconsistent position feedback id={}'.format(sid))
        if not VOLTAGE_WINDOW[0]<=v['voltage']<=VOLTAGE_WINDOW[1]:
            raise RuntimeError('Servo {} voltage outside {}..{}V'.format(sid,*VOLTAGE_WINDOW))
        if not 0<=v['temperature']<55 or not 0<=v['load_raw']<LOAD_HARD_LIMIT_RAW:
            raise RuntimeError('Servo {} temperature/load fault'.format(sid))
