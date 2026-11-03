"""Direct final endpoints at controlled speed; nonblocking motion supervision.
RAM unicast writes/readbacks and current-position ARM reuse the verified driver.
New observations may replace goals between any two UART transactions. No settle
loop and no interpolated motion goals. Faults are latched by the worker.
"""
import time
from hand_bus import IDS, packet, word, speed_raw
from hand_endpoints import check_raw, health, SPEED_RADIANS, FEEDBACK_MARGIN_RAW, LIMITS, LOAD_WARN_RAW, LOAD_WARN_SECONDS, LOAD_HARD_LIMIT_RAW

# This only qualifies the reported servo motion state. It NEVER blocks sending
# a new gesture/target: move_latest continues every loop, including while settling.
SETTLE_FEEDBACK_SECONDS = .20
SETTLE_SPAN_RAW = 1
ARRIVAL_TOLERANCE_RAW = 15  # User-requested target tracking tolerance, not extra travel.
PATH_MARGIN_RAW = 30  # Wider per-command trajectory allowance; global envelope remains +/-15.

class DriveFault(RuntimeError):
    def __init__(self,message,details):
        self.details=details
        RuntimeError.__init__(self,message+' '+str(details))

class Cancelled(RuntimeError):
    pass

class DirectDrive(object):
    def __init__(self,bus,emit,clock=time.monotonic,sleep=time.sleep):
        self.bus=bus;self.emit=emit;self.clock=clock;self.sleep=sleep
        self.mask={i:0 for i in IDS};self.commanded={};self.motion={}
        self.may_enabled=False
        self.last_feedback={}
        self.load_warnings={}

    def check_torque(self):
        actual={i:self.bus.read(i,40,1)[0] for i in IDS}
        if actual!=self.mask:
            raise RuntimeError('Torque mask mismatch expected={} actual={}'.format(self.mask,actual))

    def release(self):
        self.bus.torque(False)
        self.mask={i:0 for i in IDS}
        self.check_torque()
        self.may_enabled=False;self.commanded={};self.motion={};self.load_warnings={}
        self.emit('TORQUE_OFF_VERIFIED')

    def check_load_deadlines(self):
        # Uses cached feedback only. No sleeps/retries and no target-change reset.
        now=self.clock()
        for sid,w in list(self.load_warnings.items()):
            if now>=w['deadline']:
                self.position_fault('Load warning deadline expired',sid,
                    self.last_feedback[sid],load_warning=dict(w),observed_at=now,
                    warning_limit_raw=LOAD_WARN_RAW,hard_limit_raw=LOAD_HARD_LIMIT_RAW)

    def inspect(self,sid):
        self.check_load_deadlines()
        v=self.bus.feedback(sid)
        self.last_feedback[sid]=dict(v)
        try:health({sid:v})
        except (RuntimeError,ValueError) as exc:self.position_fault(str(exc),sid,v)
        now=self.clock()
        # A potentially blocking feedback read must not silently extend a window.
        self.check_load_deadlines()
        if v['load_raw']>=LOAD_WARN_RAW:
            if not self.mask[sid]:
                self.position_fault('Elevated load before ARM',sid,v,
                    warning_limit_raw=LOAD_WARN_RAW,hard_limit_raw=LOAD_HARD_LIMIT_RAW)
            if sid not in self.load_warnings:
                w=dict(started=now,deadline=now+LOAD_WARN_SECONDS,
                    start_raw=v['raw'],peak_load_raw=v['load_raw'],samples=1)
                self.load_warnings[sid]=w
                self.emit('LOAD_WARNING_STARTED',sid=sid,load_raw=v['load_raw'],
                    position_raw=v['raw'],deadline=w['deadline'],
                    warning_limit_raw=LOAD_WARN_RAW,hard_limit_raw=LOAD_HARD_LIMIT_RAW)
            else:
                w=self.load_warnings[sid]
                w['peak_load_raw']=max(w['peak_load_raw'],v['load_raw'])
                w['samples']+=1
        elif sid in self.load_warnings:
            w=self.load_warnings.pop(sid)
            self.emit('LOAD_WARNING_CLEARED',sid=sid,load_raw=v['load_raw'],
                duration_seconds=now-w['started'],peak_load_raw=w['peak_load_raw'],
                position_delta_raw=v['raw']-w['start_raw'])
        if self.bus.read(sid,44,2)!=word(0):
            raise RuntimeError('Nonzero goal_time id={}'.format(sid))
        if self.bus.read(sid,40,1)[0]!=self.mask[sid]:
            raise RuntimeError('Torque changed id={}'.format(sid))
        return v

    def write(self,sid,address,value,seed=False):
        self.check_load_deadlines()
        if sid not in IDS or address not in (42,46):raise ValueError('RAM whitelist')
        if address==46 and value!=speed_raw(SPEED_RADIANS):raise ValueError('Fixed configured speed only')
        if address==42:check_raw(sid,value,feedback=seed)
        self.bus.send(packet(sid,3,bytes(bytearray([address]))+word(value)))
        self.sleep(.005)
        if self.bus.read(sid,address,2)!=word(value):
            raise RuntimeError('Register readback mismatch id={} addr={}'.format(sid,address))

    def prepare(self):
        # Verify all feedback before any ARM/goal, and write only the configured speed; never use zero/unlimited.
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

    def position_fault(self,reason,sid,v,**extra):
        details=dict(sid=sid,measured_raw=v['raw'],target_raw=self.commanded.get(sid),
            error_raw=v['raw']-self.commanded[sid] if sid in self.commanded else None,
            voltage=v['voltage'],temperature=v['temperature'],load_raw=v['load_raw'],
            arrival_tolerance_raw=ARRIVAL_TOLERANCE_RAW)
        details.update(extra)
        raise DriveFault(reason+' id={}'.format(sid),details)

    def fault_snapshot(self):
        # Cached only: fault handling must release before any further UART query.
        return dict(commanded_raw=dict(self.commanded),torque_expected=dict(self.mask),
                    last_feedback={i:dict(v) for i,v in self.last_feedback.items()},
                    moving_ids=sorted(self.motion),
                    load_warnings={i:dict(w) for i,w in self.load_warnings.items()},
                    motion_details={i:self.motion_diagnostics(m) for i,m in self.motion.items()})

    def motion_diagnostics(self,m):
        return {key:m.get(key) for key in (
            'deadline','quiet_since','quiet_min','quiet_max',
            'progress_at','progress_raw','feedback_samples')}

    def timeout_fault(self,sid,v,m,now):
        self.position_fault('Motion total timeout',sid,v,deadline=m['deadline'],
            observed_at=now,late_seconds=max(0.0,now-m['deadline']),
            settle_feedback_seconds=SETTLE_FEEDBACK_SECONDS,
            settle_span_raw=SETTLE_SPAN_RAW,
            motion_diagnostics=self.motion_diagnostics(m))

    def monitor(self,sid):
        v=self.inspect(sid)
        if self.bus.read(sid,46,2)!=word(speed_raw(SPEED_RADIANS)):
            raise RuntimeError('Speed changed id={}'.format(sid))
        if sid in self.commanded and self.bus.read(sid,42,2)!=word(self.commanded[sid]):
            raise RuntimeError('Goal changed externally id={}'.format(sid))
        m=self.motion.get(sid)
        if m:
            now=self.clock();error=abs(v['raw']-self.commanded[sid])
            samples=m.setdefault('feedback_samples',[])
            previous_sample=samples[-1] if samples else None
            samples.append([now,v['raw'],v['load_raw']])
            del samples[:-8]  # Bounded diagnostic history; no UART reads added.
            lo,hi=sorted((m['start_raw'],self.commanded[sid]))
            # Arrival tolerance is also admissible at the end of this path.
            # Do not leave the old +/-3 target-side path test as a hidden gate.
            # inspect()/health() STILL enforce each calibrated travel envelope.
            path_lo=max(0,LIMITS[sid][0]-FEEDBACK_MARGIN_RAW,
                        min(lo-PATH_MARGIN_RAW,self.commanded[sid]-ARRIVAL_TOLERANCE_RAW))
            path_hi=min(1023,LIMITS[sid][1]+FEEDBACK_MARGIN_RAW,
                        max(hi+PATH_MARGIN_RAW,self.commanded[sid]+ARRIVAL_TOLERANCE_RAW))
            if not path_lo<=v['raw']<=path_hi:
                self.position_fault('Motion outside commanded path',sid,v,
                                    path_raw=[path_lo,path_hi],path_margin_raw=PATH_MARGIN_RAW)
            if error<=ARRIVAL_TOLERANCE_RAW:
                # One feedback sample inside the error band is not proof that
                # the servo is stationary. Qualify a quiet span while continuing
                # to accept/send newer final goals without a settle wait loop.
                if m['quiet_since'] is None:
                    m['quiet_since']=now;m['quiet_min']=m['quiet_max']=v['raw']
                elif max(m['quiet_max'],v['raw'])-min(m['quiet_min'],v['raw'])>SETTLE_SPAN_RAW:
                    m['quiet_since']=now;m['quiet_min']=m['quiet_max']=v['raw']
                else:
                    m['quiet_min']=min(m['quiet_min'],v['raw'])
                    m['quiet_max']=max(m['quiet_max'],v['raw'])
                # No progress is not a fault while already inside arrival band.
                m['progress_raw']=v['raw'];m['progress_at']=now
                settled=now-m['quiet_since']>=SETTLE_FEEDBACK_SECONDS
                # An already-established quiet window may be acknowledged by
                # one slightly late feedback sample. Never grant a new settling
                # window after the motion deadline or hide a long polling gap.
                late_confirmation=(settled and previous_sample is not None and
                    m['quiet_since']+SETTLE_FEEDBACK_SECONDS<=m['deadline'] and
                    previous_sample[0]<=m['deadline'] and
                    0<=now-previous_sample[0]<=SETTLE_FEEDBACK_SECONDS and
                    now<=m['deadline']+SETTLE_FEEDBACK_SECONDS)
                if now>m['deadline'] and not late_confirmation:
                    self.timeout_fault(sid,v,m,now)
                if settled:
                    del self.motion[sid]
                    self.emit('ENDPOINT_REACHED',sid=sid,raw=v['raw'],
                        target_raw=self.commanded[sid],error_raw=v['raw']-self.commanded[sid],
                        arrival_tolerance_raw=ARRIVAL_TOLERANCE_RAW,
                        settled_feedback_seconds=now-m['quiet_since'],
                        late_confirmation_seconds=max(0.0,now-m['deadline']))
            else:
                if now>m['deadline']:
                    self.timeout_fault(sid,v,m,now)
                m['quiet_since']=None
                # Retargeting does not reset the no-movement timer.
                if abs(v['raw']-m['progress_raw'])>=2:
                    m['progress_raw']=v['raw'];m['progress_at']=now
                if now-m['progress_at']>.8:
                    self.position_fault('Motion no progress >0.8s',sid,v,
                                        no_progress_seconds=now-m['progress_at'])
        elif sid in self.commanded and abs(v['raw']-self.commanded[sid])>ARRIVAL_TOLERANCE_RAW:
            self.position_fault('Stationary position drift',sid,v)
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
            # EVERY changed goal is a motion command, including 1..3raw and
            # zero measured distance. Never infer stationary from pre-write error.
            self.motion[sid]={'start_raw':v['raw'],
                'progress_raw':old['progress_raw'] if old else v['raw'],
                'progress_at':old['progress_at'] if old else now,
                'deadline':now+duration,'quiet_since':None,
                'quiet_min':None,'quiet_max':None}
            self.emit('DIRECT_ENDPOINT',sid=sid,target_raw=raw,start_raw=v['raw'],
                      speed_raw=speed_raw(SPEED_RADIANS),motion_deadline_seconds=duration)
