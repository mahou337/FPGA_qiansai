"""Manually authorized single-frame endpoint follower, PS UART1 only."""
import argparse
import json
import os
import select
import signal
import sys
import time
from hand_bus import IDS, SerialBus
from hand_policy import Policy
from hand_endpoints import health, SPEED_RADIANS, FEEDBACK_MARGIN_RAW, VOLTAGE_WINDOW, LOAD_HARD_LIMIT_RAW, LOAD_WARN_RAW, LOAD_WARN_SECONDS
from hand_final import DirectDrive, Cancelled, ARRIVAL_TOLERANCE_RAW, PATH_MARGIN_RAW
from hand_log import HandLog
from protocol import decode

STOP=False
ACK_ENV='GESTURE_HAND_FINAL_ACK'

def on_signal(signum,frame):
    global STOP
    STOP=True

class InputStream(object):
    """Bounded pipe reader: records are validated, only latest target is retained."""
    def __init__(self,fd,policy,event,clock=time.monotonic):
        self.fd=fd;self.policy=policy;self.event=event;self.clock=clock
        self.buffer=b'';self.closed=False;self.signature=None
        self.last_byte=clock();self.started=clock()

    def drain(self):
        total=0
        while not self.closed and select.select([self.fd],[],[],0)[0]:
            data=os.read(self.fd,8192)
            if not data:self.closed=True;break
            self.last_byte=self.clock();self.buffer+=data;total+=len(data)
            if len(self.buffer)>32768 or total>65536:raise RuntimeError('IPC backlog limit')
            while b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                record=json.loads(line.decode('ascii'))
                row=decode(record['frame'].encode('ascii'))
                if row['status'] in ('STOPPED','CAPTURE_ERROR'):
                    self.closed=True;self.policy.latest=None
                    if row['status']=='CAPTURE_ERROR':raise RuntimeError('Camera capture failed')
                    return
                accepted=self.policy.feed(row,float(record['captured']),float(record['sent']),self.clock())
                signature=(self.policy.last_reason,self.policy.latest)
                if signature!=self.signature:
                    self.event('CONTROL_STATUS',seq=row['seq'],accepted=accepted,
                        raw=row['raw'],code=row['code'],status=row['status'],
                        action_code=self.policy.latest,reason=self.policy.last_reason)
                    self.signature=signature
        if self.closed and self.buffer:
            raise RuntimeError('Truncated recognition IPC record')
        now=self.clock()
        if self.policy.communication_expired(now):
            raise RuntimeError('Recognition link lost: no new LIVE capture >2s')
        if self.policy.last_received is None and now-self.started>30:
            raise RuntimeError('No LIVE camera stream >30s')

    def current(self):
        self.drain()
        return None if STOP or self.closed else self.policy.target()


def follow(drive,stream,event,log):
    """No gesture queue or blocking settle; supervise old movement each cycle."""
    def current():
        if log and log.error:raise RuntimeError('Actuator log failed: '+log.error)
        return stream.current()
    while not STOP:
        values=current()
        if stream.closed:break
        if values is None:
            if drive.may_enabled:
                drive.release();event('OBSERVATION_RELEASE',reason=stream.policy.last_reason)
            select.select([stream.fd],[],[],.02)
            continue
        try:
            if not drive.may_enabled:drive.arm(current)
            drive.move_latest(current)
        except Cancelled as exc:
            drive.release();event('OBSERVATION_RELEASE',reason=str(exc))
        # Polling cadence only: it is NOT a recognition stability/age gate.
        select.select([stream.fd],[],[],.01)


def run(worker=False,log_path=None):
    global STOP
    STOP=False
    for name in ('SIGTERM','SIGINT','SIGHUP'):
        if hasattr(signal,name):signal.signal(getattr(signal,name),on_signal)
    bus=None;drive=None;log=None;rc=1;fault=None;release_verified=False
    def event(name,**fields):
        text=json.dumps(dict(event=name,monotonic=time.monotonic(),**fields),sort_keys=True)
        if log:log.emit(text)
        else:print(text,flush=True)
    try:
        if worker:
            if os.environ.get(ACK_ENV)!='FOLLOW_FINAL':raise RuntimeError('Manual FOLLOW_FINAL authorization required')
            if log_path is None:raise RuntimeError('Log path required')
            log=HandLog(log_path)
        bus=SerialBus()
        if worker:
            drive=DirectDrive(bus,event)
            drive.release()
        feedback=bus.probe();health(feedback)
        event('PROBE_OK',identity=bus.identity,servos=feedback,read_only=not worker)
        if worker:
            drive.prepare()
            event('CONTROL_POLICY',version='single-frame-direct-endpoints-tol15',confirmation_frames=1,
                  frame_age_gate=False,open_pose_arming_gate=False,
                  candidate_states=['PENDING','CONFIRMED'],link_loss_timeout=2.0,
                  voltage_window=list(VOLTAGE_WINDOW),feedback_margin_raw=FEEDBACK_MARGIN_RAW,path_margin_raw=PATH_MARGIN_RAW,
                  arrival_tolerance_raw=ARRIVAL_TOLERANCE_RAW,stationary_error_tolerance_raw=ARRIVAL_TOLERANCE_RAW,
                  load_hard_limit_raw=LOAD_HARD_LIMIT_RAW,load_warning_raw=LOAD_WARN_RAW,
                  load_warning_seconds=LOAD_WARN_SECONDS,
                  speed_radians=SPEED_RADIANS,invalid_action='release_no_inferred_goal',
                  servo_settle_qualification_seconds=.20,settle_never_blocks_new_target=True)
            print('READY',flush=True)
            stream=InputStream(sys.stdin.fileno(),Policy(),event)
            follow(drive,stream,event,log)
            event('STOP_REQUESTED')
        rc=0
    except BaseException as exc:
        fault=str(exc)
        # Capture cached evidence before release clears commands; no UART query.
        diagnostics=drive.fault_snapshot() if drive else None
        if drive:
            try:drive.release()
            except Exception:pass
        try:event('FAULT',error=fault,details=getattr(exc,'details',None),diagnostics=diagnostics)
        except Exception:pass
        print('HAND_FAULT: '+fault,file=sys.stderr,flush=True)
        rc=1
    finally:
        if bus is not None:
            if worker and drive:
                try:
                    drive.release()
                    release_verified=True
                except Exception as exc:
                    rc=1
                    print('RELEASE_NOT_CONFIRMED: CUT SERVO POWER: '+str(exc),file=sys.stderr,flush=True)
            try:bus.close()
            except Exception as exc:
                rc=1
                print('HAND_BUS_CLOSE_FAILED: '+str(exc),file=sys.stderr,flush=True)
        if log and not log.close():
            print('HAND_LOG_NOT_FULLY_SAVED',file=sys.stderr,flush=True);rc=1
        if worker:
            # Dedicated final IPC acknowledgement, independent of SD event log.
            # An ordinary fault with verified torque-off remains rc=1, but is
            # not falsely reported by the parent as an unverified release.
            status=dict(kind='HAND_EXIT',return_code=rc,
                        release_verified=release_verified,error=fault[:1024] if fault else None)
            try:print(json.dumps(status,sort_keys=True),flush=True)
            except (OSError,IOError):rc=1
    return rc

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--probe',action='store_true');mode.add_argument('--worker',action='store_true')
    p.add_argument('--log');a=p.parse_args();sys.exit(run(a.worker,a.log))
