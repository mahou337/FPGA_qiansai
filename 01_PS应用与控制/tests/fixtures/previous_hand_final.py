"""Direct final endpoints at controlled speed; nonblocking motion supervision.
RAM unicast writes/readbacks and current-position ARM reuse the verified driver.
New observations may replace goals between any two UART transactions. No settle
loop and no interpolated motion goals. Faults are latched by the worker.
"""
import time
from hand_bus import IDS, packet, word, speed_raw
from hand_endpoints import check_raw, health, SPEED_RADIANS

class Cancelled(RuntimeError):
    pass

class DirectDrive(object):
    def __init__(self,bus,emit,clock=time.monotonic,sleep=time.sleep):
        self.bus=bus;self.emit=emit;self.clock=clock;self.sleep=sleep
        self.mask={i:0 for i in IDS};self.commanded={};self.motion={}
        self.may_enabled=False

    def check_torque(self):
        actual={i:self.bus.read(i,40,1)[0] for i in IDS}
        if actual!=self.mask:
            raise RuntimeError('Torque mask mismatch expected={} actual={}'.format(self.mask,actual))

    def release(self):
        self.bus.torque(False)
        self.mask={i:0 for i in IDS}
        self.check_torque()
        self.may_enabled=False;self.commanded={};self.motion={}
        self.emit('TORQUE_OFF_VERIFIED')

    def inspect(self,sid):
        v=self.bus.feedback(sid);health({sid:v})
        if self.bus.read(sid,44,2)!=word(0):
            raise RuntimeError('Nonzero goal_time id={}'.format(sid))
        if self.bus.read(sid,40,1)[0]!=self.mask[sid]:
            raise RuntimeError('Torque changed id={}'.format(sid))
        return v

    def write(self,sid,address,value,seed=False):
        if sid not in IDS or address not in (42,46):raise ValueError('RAM whitelist')
        if address==46 and value!=speed_raw(SPEED_RADIANS):raise ValueError('Fixed low speed only')
        if address==42:check_raw(sid,value,feedback=seed)
        self.bus.send(packet(sid,3,bytes(bytearray([address]))+word(value)))
        self.sleep(.005)
        if self.bus.read(sid,address,2)!=word(value):
            raise RuntimeError('Register readback mismatch id={} addr={}'.format(sid,address))

    def prepare(self):
        # Verify all feedback before any ARM/goal, and write only low speed.
        for sid in IDS:self.inspect(sid)
        self.check_torque()
        for sid in IDS:
            if self.bus.read(sid,46,2)!=word(speed_raw(SPEED_RADIANS)):
                self.write(sid,46,speed_raw(SPEED_RADIANS));self.check_torque()

    def arm(self,current):
        began=self.clock()
        for sid in IDS:self.inspect(sid)
        for sid in IDS:
            if current() is None:raise Cancelled('No usable observation during ARM')
            if self.clock()-began>3.0:raise RuntimeError('ARM communication transaction >3s')
            v=self.inspect(sid)
            if self.bus.read(sid,46,2)!=word(speed_raw(SPEED_RADIANS)):
                raise RuntimeError('Speed changed before ARM')
            if current() is None:raise Cancelled('No usable observation before seed')
            self.may_enabled=True  # goal writes can enable even if readback fails
            self.write(sid,42,v['raw'],seed=True)
            self.mask[sid]=1;self.commanded[sid]=v['raw'];self.check_torque()
            after=self.inspect(sid)
            if abs(after['raw']-v['raw'])>3:raise RuntimeError('Movement during current-position ARM')
        self.emit('ARMED',seed_raw=dict(self.commanded))

    def monitor(self,sid):
        v=self.inspect(sid)
        if self.bus.read(sid,46,2)!=word(speed_raw(SPEED_RADIANS)):
            raise RuntimeError('Speed changed id={}'.format(sid))
        if sid in self.commanded and self.bus.read(sid,42,2)!=word(self.commanded[sid]):
            raise RuntimeError('Goal changed externally id={}'.format(sid))
        m=self.motion.get(sid)
        if m:
            now=self.clock();error=abs(v['raw']-self.commanded[sid])
            if error<=3:
                del self.motion[sid]
                self.emit('ENDPOINT_REACHED',sid=sid,raw=v['raw'],target_raw=self.commanded[sid])
            else:
                # Retargeting does not reset the no-movement timer.
                if abs(v['raw']-m['progress_raw'])>=2:
                    m['progress_raw']=v['raw'];m['progress_at']=now
                if now-m['progress_at']>.8:
                    raise RuntimeError('Motion no progress >0.8s id={}'.format(sid))
                if now>m['deadline']:
                    raise RuntimeError('Motion total timeout id={}'.format(sid))
                lo,hi=sorted((m['start_raw'],self.commanded[sid]))
                if not lo-3<=v['raw']<=hi+3:
                    raise RuntimeError('Motion outside commanded path id={}'.format(sid))
        elif sid in self.commanded and abs(v['raw']-self.commanded[sid])>3:
            raise RuntimeError('Stationary position drift id={}'.format(sid))
        return v

    def move_latest(self,current):
        if self.mask!={i:1 for i in IDS}:raise RuntimeError('All servos must be armed')
        for sid in IDS:
            # Drain all available records before monitoring and again before
            # committing a goal, so a changed target never waits for old travel.
            values=current()
            if values is None:raise Cancelled('Observation unusable')
            if set(values)!=set(IDS):raise ValueError('Incomplete target')
            for i in IDS:check_raw(i,values[i])
            v=self.monitor(sid)
            values=current()
            if values is None:raise Cancelled('Observation unusable before write')
            if set(values)!=set(IDS):raise ValueError('Incomplete target')
            for i in IDS:check_raw(i,values[i])
            raw=values[sid]
            if raw==self.commanded[sid]:continue
            now=self.clock();old=self.motion.get(sid)
            distance=abs(raw-v['raw'])
            duration=2.0+2.0*distance/speed_raw(SPEED_RADIANS)
            self.write(sid,42,raw);self.commanded[sid]=raw;self.check_torque()
            if distance>3:
                self.motion[sid]={'start_raw':v['raw'],
                    'progress_raw':old['progress_raw'] if old else v['raw'],
                    'progress_at':old['progress_at'] if old else now,
                    'deadline':now+duration}
            else:self.motion.pop(sid,None)
            self.emit('DIRECT_ENDPOINT',sid=sid,target_raw=raw,start_raw=v['raw'],
                      speed_raw=speed_raw(SPEED_RADIANS),motion_deadline_seconds=duration)
