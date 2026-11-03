"""One new complete LIVE observation; no count, age or open-hand arming gate.
A watchdog measures delivery of new LIVE captures, including unknown/no-hand,
not time since CONFIRMED. It is a link failure detector, never a dwell period.
"""
import math
from hand_endpoints import targets

class Policy(object):
    def __init__(self, max_silence=2.0):
        self.max_silence=max_silence
        self.last_seq=-1
        self.last_capture=None
        self.last_received=None
        self.latest=None
        self.last_reason='no_observation'

    def feed(self,row,captured,sent,now):
        if not all(math.isfinite(x) for x in (captured,sent,now)):
            raise ValueError('Nonfinite timestamp')
        if row['seq']<=self.last_seq:
            raise ValueError('Duplicate/out-of-order record')
        self.last_seq=row['seq']
        if not captured<=sent<=now:
            raise ValueError('Timestamp order')
        if self.last_capture is not None and captured<=self.last_capture:
            self.latest=None;self.last_reason='capture_not_new'
            return False
        self.last_capture=captured
        if row['source']!='LIVE':
            self.latest=None;self.last_reason='not_live'
            return False
        self.last_received=now
        raw=row['raw']
        if (row['status'] not in ('PENDING','CONFIRMED') or
                len(raw)!=4 or set(raw)-set('01')):
            self.latest=None;self.last_reason='not_complete_current_observation'
            return False
        if row['status']=='CONFIRMED' and (not row['valid'] or row['code']!=raw):
            self.latest=None;self.last_reason='inconsistent_confirmed'
            return False
        self.latest=raw  # PENDING.code may be last stable pose: deliberately ignored.
        self.last_reason='single_current_frame'
        return True

    def communication_expired(self,now):
        return self.last_received is not None and now-self.last_received>self.max_silence

    def target(self):
        return targets(self.latest) if self.latest is not None else None
