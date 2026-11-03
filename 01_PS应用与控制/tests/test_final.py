import itertools,json,os,sys,tempfile,time,threading,unittest,signal,io,contextlib
from pathlib import Path
from unittest import mock
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import IDS,PAIRS,OPEN,CLOSED,LIMITS,targets,check_raw,health,SPEED_RADIANS
from hand_bus import raw_angle,speed_raw,word,angle_raw,sync_packet
from hand_policy import Policy
from hand_final import DirectDrive,Cancelled
from protocol import encode,decode
import hand_worker

class Clock:
 def __init__(self):self.t=10.
 def __call__(self):return self.t
 def advance(self,x):self.t+=x

class FakeBus:
 identity={'test':'memory-only; NOT physical UART'}
 def __init__(self):
  self.pos={i:(OPEN[i]+CLOSED[i])//2 for i in IDS}
  self.reg={i:{40:0,42:self.pos[i],44:0,46:0} for i in IDS}
  self.health={i:dict(voltage=7.5,temperature=22,load_raw=0) for i in IDS}
  self.calls=[];self.instant=True;self.fail_goal=None;self.fail_after_enable=None
  self.stuck_torque=False;self.closed=False;self.on_goal=None
 @property
 def enabled(self):return any(self.reg[i][40] for i in IDS)
 def probe(self):return {i:self.feedback(i) for i in IDS}
 def feedback(self,sid):
  v=dict(self.health[sid]);v.update(raw=self.pos[sid],angle=raw_angle(self.pos[sid]));return v
 def read(self,sid,addr,n):
  return bytes(bytearray([self.reg[sid][addr]])) if n==1 else word(self.reg[sid][addr])
 def send(self,frame):
  assert frame[:2]==b'\xff\xff' and sum(bytearray(frame[2:]))&255==255
  sid,ins,addr=frame[2],frame[4],frame[5]
  assert sid in IDS and ins==3 and addr in (42,46) and len(frame)==9
  value=frame[6]*256+frame[7]
  if addr==42 and self.fail_goal==sid:raise RuntimeError('UART write fault')
  self.reg[sid][addr]=value;self.calls.append((addr,sid,value))
  if addr==42:
   self.reg[sid][40]=1
   if self.instant:self.pos[sid]=value
   if self.on_goal:self.on_goal(sid,value)
   if self.fail_after_enable==sid:raise RuntimeError('UART fault after enable')
 def torque(self,enabled):
  assert enabled is False
  self.calls.append((40,0,0))
  if not self.stuck_torque:
   for i in IDS:self.reg[i][40]=0
 def close(self):self.closed=True

def row(seq=0,raw='0000',status='CONFIRMED',code=None,source='LIVE'):
 result=dict(status=status,code=raw if code is None else code,raw={'code':raw},reliable=True)
 return decode(encode(seq,seq*100,result,source))

class PolicyTests(unittest.TestCase):
 def test_sixteen_exact_raw_maps(self):
  for bits in itertools.product('01',repeat=4):
   code=''.join(bits);v=targets(code)
   for bit,pair in zip(bits,PAIRS):
    for sid in pair:self.assertEqual(v[sid],(OPEN if bit=='1' else CLOSED)[sid])
 def test_first_closed_frame_eligible(self):
  p=Policy();self.assertTrue(p.feed(row(),1,1.1,1.2));self.assertEqual(p.target(),CLOSED)
 def test_pending_current_raw_not_previous_code(self):
  p=Policy();p.feed(row(raw='0101',status='PENDING',code='1111'),1,1.1,1.2)
  self.assertEqual(p.target(),targets('0101'))
 def test_long_processing_no_age_cutoff(self):
  p=Policy();self.assertTrue(p.feed(row(),1,3,3.1));self.assertEqual(p.target(),CLOSED)
 def test_no_confirmation_interval_gate(self):
  p=Policy();p.feed(row(),1,1,1);p.feed(row(1,raw='1111'),2.2,2.2,2.2)
  self.assertEqual(p.target(),OPEN)
 def test_newest_replaces_without_queue(self):
  p=Policy()
  for i,c in enumerate(['0000','1111','1010']):p.feed(row(i,c),i+1,i+1,i+1)
  self.assertEqual(p.target(),targets('1010'))
 def test_invalid_never_infers(self):
  for status,raw in [('NO_HAND','0000'),('UNKNOWN','1111'),('PARTIAL','01??'),('HOLD','1111'),('PENDING','1?01'),('STALE','1111')]:
   p=Policy();self.assertFalse(p.feed(row(raw=raw,status=status),1,1,1));self.assertIsNone(p.target())
 def test_replay_refused(self):
  p=Policy();self.assertFalse(p.feed(row(source='REPLAY'),1,1,1));self.assertIsNone(p.last_received)
 def test_duplicate_sequence_fault(self):
  p=Policy();p.feed(row(),1,1,1)
  with self.assertRaises(ValueError):p.feed(row(),2,2,2)
 def test_old_capture_no_watchdog_refresh(self):
  p=Policy();p.feed(row(),1,1,1);self.assertFalse(p.feed(row(1),1,2,2));self.assertEqual(p.last_received,1)
 def test_bad_timestamps_fault(self):
  for cap,sent,now in [(2,1,3),(1,3,2),(float('nan'),2,3)]:
   with self.assertRaises(ValueError):Policy().feed(row(),cap,sent,now)
 def test_contradictory_confirmed_refused(self):
  p=Policy();r=row();r['code']='1111'
  self.assertFalse(p.feed(r,1,1,1));self.assertIsNone(p.target())
 def test_link_liveness_not_confirmation(self):
  p=Policy();p.feed(row(),1,1,1)
  p.feed(row(1,raw='????',status='UNKNOWN'),2.5,2.5,2.5)
  self.assertFalse(p.communication_expired(4));self.assertTrue(p.communication_expired(4.51))
 def test_endpoint_provenance_matches_confirmed_record(self):
  record=json.loads((B/'delivery/open_closed_observed_214705.json').read_text())
  confirmation=json.loads((B/'delivery/USER_CONFIRMED_ENDPOINTS_AND_FINAL_REQUIREMENTS.json').read_text())
  self.assertTrue(confirmation['user_confirmed_open_closed_calibration'])
  for finger,values in record['fingers'].items():
   for sid,raw in values['open']['raw'].items():self.assertEqual(OPEN[int(sid)],raw)
  active=json.loads((B/'delivery/ACTIVE_ENDPOINTS.json').read_text())
  self.assertTrue(active['user_confirmed_new_closed_endpoints'])
  for sid,raw in active['closed_raw'].items():self.assertEqual(CLOSED[int(sid)],raw)
 def test_bad_codes(self):
  for code in ['?111','111','11111','ab01',None]:
   with self.assertRaises(ValueError):targets(code)

class DriveTests(unittest.TestCase):
 def setup_drive(self,arm=True):
  b=FakeBus();c=Clock();events=[]
  d=DirectDrive(b,lambda n,**k:events.append((n,k)),clock=c,sleep=lambda x:None)
  d.release();d.prepare()
  if arm:d.arm(lambda:CLOSED)
  return b,d,c,events
 def test_exact_arm_seed_not_zero(self):
  b,d,c,e=self.setup_drive()
  self.assertEqual([x for x in b.calls if x[0]==42],[(42,i,(OPEN[i]+CLOSED[i])//2) for i in IDS])
 def test_sixteen_direct_no_intermediate_goals(self):
  b,d,c,e=self.setup_drive()
  for bits in itertools.product('01',repeat=4):
   values=targets(''.join(bits));n=len(b.calls);d.move_latest(lambda:values)
   self.assertEqual(d.commanded,values)
   for addr,sid,v in b.calls[n:]:
    if addr==42:self.assertEqual(v,values[sid])
 def test_duplicate_target_no_resend(self):
  b,d,c,e=self.setup_drive();d.move_latest(lambda:CLOSED);n=len(b.calls)
  for i in range(10):d.move_latest(lambda:CLOSED)
  self.assertEqual(len(b.calls),n)
 def test_pending_motion_superseded_without_settle(self):
  b,d,c,e=self.setup_drive();b.instant=False;d.move_latest(lambda:CLOSED)
  self.assertTrue(d.motion);d.move_latest(lambda:OPEN);self.assertEqual(d.commanded,OPEN)
 def test_mid_batch_latest_target(self):
  b,d,c,e=self.setup_drive();latest=[CLOSED]
  b.on_goal=lambda sid,value:latest.__setitem__(0,OPEN) if sid==1 else None
  n=len(b.calls);d.move_latest(lambda:latest[0])
  for addr,sid,v in b.calls[n:]:
   if addr==42:self.assertEqual(v,CLOSED[1] if sid==1 else OPEN[sid])
  d.move_latest(lambda:latest[0]);self.assertEqual(d.commanded,OPEN)
 def test_invalid_mid_arm_cancels_and_releases(self):
  b,d,c,e=self.setup_drive(False);calls=[0]
  def current():
   calls[0]+=1;return CLOSED if calls[0]<4 else None
  with self.assertRaises(Cancelled):d.arm(current)
  d.release();self.assertFalse(b.enabled)
 def test_no_age_callback_during_long_arm(self):
  b,d,c,e=self.setup_drive(False)
  b.on_goal=lambda sid,value:c.advance(.12)
  d.arm(lambda:CLOSED);self.assertGreater(c.t-10,.75);self.assertTrue(b.enabled)
 def test_non_symmetric_over_100_accepted(self):
  b,d,c,e=self.setup_drive();d.move_latest(lambda:CLOSED)
  self.assertEqual(b.pos[3],90);self.assertEqual(b.pos[4],989)
  self.assertLess(raw_angle(b.pos[3]),-100);self.assertGreater(raw_angle(b.pos[4]),100)
  self.assertGreater(abs(raw_angle(b.pos[3])+raw_angle(b.pos[4])),12)
 def test_position_and_voltage_boundaries(self):
  for sid in IDS:
   lo,hi=LIMITS[sid]
   for raw in [lo,hi]:check_raw(sid,raw)
   for raw in [lo-1,hi+1]:
    with self.assertRaises(RuntimeError):check_raw(sid,raw)
   for raw in [lo-15,hi+15]:check_raw(sid,raw,True)
   for raw in [lo-16,hi+16]:
    with self.assertRaises(RuntimeError):check_raw(sid,raw,True)
   for voltage in [4.5,7.5,7.6]:
    health({sid:dict(raw=lo,angle=raw_angle(lo),voltage=voltage,temperature=54,load_raw=699)})
 def test_health_faults_before_arm(self):
  for k,v in [('voltage',4.4),('voltage',7.7),('voltage',float('nan')),('temperature',55),('load_raw',700)]:
   b,d,c,e=self.setup_drive(False);b.health[3][k]=v
   with self.assertRaises(RuntimeError):d.arm(lambda:CLOSED)
   self.assertFalse(b.enabled)
 def test_start_outside_range_no_goal(self):
  b,d,c,e=self.setup_drive(False);b.pos[1]=LIMITS[1][0]-16
  with self.assertRaises(RuntimeError):d.arm(lambda:CLOSED)
  self.assertFalse([x for x in b.calls if x[0]==42])
 def test_whole_target_checked_before_goal(self):
  b,d,c,e=self.setup_drive();v=dict(OPEN);v[8]=1023;n=len(b.calls)
  with self.assertRaises(RuntimeError):d.move_latest(lambda:v)
  self.assertEqual(n,len(b.calls))
 def test_readback_mismatch_fault(self):
  b,d,c,e=self.setup_drive();original=b.read
  b.read=lambda sid,addr,n:word(0) if addr==42 else original(sid,addr,n)
  with self.assertRaises(RuntimeError):d.move_latest(lambda:CLOSED)
  d.release();self.assertFalse(b.enabled)
 def test_no_progress_fault(self):
  b,d,c,e=self.setup_drive();b.instant=False;d.move_latest(lambda:CLOSED);c.advance(.81)
  with self.assertRaisesRegex(RuntimeError,'no progress'):d.monitor(1)
 def test_retarget_does_not_hide_stall(self):
  b,d,c,e=self.setup_drive();b.instant=False;d.move_latest(lambda:CLOSED)
  c.advance(.4);d.move_latest(lambda:OPEN);c.advance(.41)
  with self.assertRaisesRegex(RuntimeError,'no progress'):d.monitor(1)
 def test_total_motion_timeout(self):
  b,d,c,e=self.setup_drive();b.instant=False;d.move_latest(lambda:CLOSED)
  c.t=d.motion[1]['deadline']+.01;b.pos[1]-=2
  with self.assertRaisesRegex(RuntimeError,'total timeout'):d.monitor(1)
 def test_full_travel_progresses_without_five_degree_tracking_limit(self):
  b,d,c,e=self.setup_drive();b.instant=False;d.move_latest(lambda:CLOSED)
  for step in range(90):
   c.advance(.1)
   for sid in IDS:
    delta=CLOSED[sid]-b.pos[sid];step_raw=max(4,int(speed_raw(SPEED_RADIANS)*.1));b.pos[sid]+=max(-step_raw,min(step_raw,delta))
   d.move_latest(lambda:CLOSED)
  self.assertEqual(b.pos,CLOSED);self.assertEqual(d.motion,{})
 def test_requested_speed_is_977(self):
  b,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  self.assertEqual(speed_raw(.25),48)
  self.assertEqual(speed_raw(5.0),977)
  self.assertTrue(all(b.reg[i][46]==977 for i in IDS))
 def test_register_torque_and_position_faults(self):
  for addr,v in [(40,0),(44,1),(46,0),(42,511)]:
   b,d,c,e=self.setup_drive();b.reg[1][addr]=v
   with self.assertRaises(RuntimeError):d.monitor(1)
 def test_stationary_drift(self):
  b,d,c,e=self.setup_drive();b.pos[1]+=16
  with self.assertRaisesRegex(RuntimeError,'drift'):d.monitor(1)
 def test_generic_helpers_use_individual_bounds(self):
  for sid in IDS:self.assertEqual(angle_raw(raw_angle(CLOSED[sid])),CLOSED[sid])
  sync_packet(42,CLOSED)
  bad=dict(OPEN);bad[1]+=1
  with self.assertRaises(RuntimeError):sync_packet(42,bad)

@unittest.skipUnless(os.name=='posix','POSIX pipe/worker')
class WorkerTests(unittest.TestCase):
 def scenario(self,mode):
  bus=FakeBus();read,write=os.pipe();stub=mock.Mock();stub.fileno.return_value=read
  if mode=='partial_arm':bus.fail_after_enable=3
  if mode=='release_failure':bus.stuck_torque=True
  before=[];errors=[]
  def producer():
   try:
    time.sleep(.03)
    for seq,raw,status,age in [(0,'0000','PENDING',1.2),(1,'1111','PENDING',.01)]:
     now=time.monotonic();frame=encode(seq,seq*100,dict(status=status,code='1010',raw={'code':raw},reliable=True))
     os.write(write,(json.dumps(dict(frame=frame.decode(),captured=now-age,sent=now))+'\n').encode())
     time.sleep(.25)
    if mode=='unknown':
     now=time.monotonic();frame=encode(2,300,dict(status='UNKNOWN',code='1111',raw={'code':'????'},reliable=False))
     os.write(write,(json.dumps(dict(frame=frame.decode(),captured=now,sent=now))+'\n').encode());time.sleep(.15)
     before.append(bus.enabled)
    if mode=='silence':time.sleep(2.2)
    if mode=='signal':os.kill(os.getpid(),signal.SIGTERM);time.sleep(.1)
   except (OSError,Exception) as exc:errors.append(str(exc))
   finally:os.close(write)
  OriginalLog=hand_worker.HandLog
  class Log(OriginalLog):
   def emit(self,text):
    if mode=='goal_failure' and '"event": "ARMED"' in text:bus.fail_goal=4
    if mode=='log_failure' and '"event": "ARMED"' in text:
     self.error='simulated disk fault';raise RuntimeError(self.error)
    return super(Log,self).emit(text)
  with tempfile.TemporaryDirectory() as name:
   log=str(Path(name)/'events.jsonl');thread=threading.Thread(target=producer);thread.start()
   with mock.patch.object(hand_worker,'SerialBus',return_value=bus),mock.patch.object(hand_worker.sys,'stdin',stub),mock.patch.dict(os.environ,{hand_worker.ACK_ENV:'FOLLOW_FINAL'}),mock.patch.object(hand_worker,'HandLog',Log):
    out=io.StringIO()
    with contextlib.redirect_stdout(out):rc=hand_worker.run(True,log)
    bus.worker_stdout=out.getvalue()
   thread.join(5);os.close(read);events=[json.loads(s) for s in Path(log).read_text().splitlines()]
  self.assertTrue(bus.closed)
  if mode!='release_failure':self.assertFalse(bus.enabled)
  return bus,rc,events,before
 def test_worker_single_pending_direct_and_eof(self):
  b,rc,e,_=self.scenario('eof');self.assertEqual(rc,0)
  direct=[x for x in e if x['event']=='DIRECT_ENDPOINT'];self.assertTrue(direct)
  self.assertTrue(any(x['target_raw']==CLOSED[x['sid']] for x in direct))
 def test_unknown_releases_not_previous_stable(self):
  b,rc,e,before=self.scenario('unknown');self.assertEqual(rc,0);self.assertEqual(before,[False])
 def test_link_loss_fault_release(self):
  b,rc,e,_=self.scenario('silence');self.assertEqual(rc,1)
  self.assertTrue(any('link lost' in x.get('error','') for x in e))
 def test_partial_arm_fault_release(self):self.assertEqual(self.scenario('partial_arm')[1],1)
 def test_uart_final_goal_failure_releases_all(self):self.assertEqual(self.scenario('goal_failure')[1],1)
 def test_signal_release(self):self.assertEqual(self.scenario('signal')[1],0)
 def test_log_failure_release(self):self.assertEqual(self.scenario('log_failure')[1],1)
 def test_release_failure_nonzero(self):self.assertEqual(self.scenario('release_failure')[1],1)
 def test_no_authorization_no_bus(self):
  with mock.patch.object(hand_worker,'SerialBus') as factory,mock.patch.dict(os.environ,{hand_worker.ACK_ENV:''}):
   self.assertEqual(hand_worker.run(True,'unused'),1);factory.assert_not_called()
 def test_probe_failure_no_writes(self):
  b=FakeBus();b.health[1]['voltage']=8
  with mock.patch.object(hand_worker,'SerialBus',return_value=b):self.assertEqual(hand_worker.run(False),1)
  self.assertEqual(b.calls,[])

@unittest.skipUnless(os.name=='posix','POSIX IPC')
class StreamTests(unittest.TestCase):
 def make(self):
  r,w=os.pipe();self.addCleanup(os.close,r);self.addCleanup(os.close,w)
  p=Policy();stream=hand_worker.InputStream(r,p,lambda *a,**kw:None)
  hand_worker.STOP=False
  return w,stream,p
 def send(self,w,seq,raw,status='PENDING',source='LIVE',captured=None):
  now=time.monotonic()
  packet=encode(seq,seq,dict(status=status,code='1111',raw={'code':raw},reliable=True),source)
  os.write(w,(json.dumps(dict(frame=packet.decode(),captured=now if captured is None else captured,sent=now))+'\n').encode())
 def test_backlog_only_latest_action(self):
  w,s,p=self.make()
  for i,code in enumerate(['0000','1111','1001','0110']):self.send(w,i,code)
  self.assertEqual(s.current(),targets('0110'));self.assertEqual(p.last_seq,3)
 def test_backlog_latest_unknown_cancels_all(self):
  w,s,p=self.make();self.send(w,0,'0000');self.send(w,1,'????','UNKNOWN')
  self.assertIsNone(s.current())
 def test_bad_crc_fault(self):
  w,s,p=self.make();os.write(w,b'{"frame":"$G1,0,0,LIVE,0000,0000,CONFIRMED,1,0*0000\\r\\n","captured":1,"sent":1}\n')
  with self.assertRaises(ValueError):s.current()
 def test_same_capture_is_not_new_data(self):
  w,s,p=self.make();cap=time.monotonic();self.send(w,0,'0000',captured=cap);s.current()
  self.send(w,1,'1111',captured=cap);self.assertIsNone(s.current())
 def test_replay_never_enables(self):
  w,s,p=self.make();self.send(w,0,'1111',source='REPLAY');self.assertIsNone(s.current())

class SourceAndRecognitionTests(unittest.TestCase):
 def test_no_age_count_step_gates_in_runtime(self):
  s=(B/'delivery/app/ps/run.py').read_text()
  for x in ['args.max_gap','guard_age(','stale_serial','stale_processing','frame_gap']:self.assertNotIn(x,s)
  for n in ['hand_policy.py','hand_worker.py','hand_final.py']:
   s=(B/'delivery/app/ps'/n).read_text()
   for x in ['.75','candidate_count','open_count','ObservationExpired','FOLLOW15','-100 <=']:self.assertNotIn(x,s)
 def test_no_images_and_manual_launcher(self):
  s=(B/'delivery/start_follow.py').read_text()
  self.assertIn("'--no-images'",s);self.assertIn('FOLLOW_FINAL',s)
  self.assertNotIn('two raw1111',s)
 def test_actual_recognition_first_frame_confirms(self):
  try:import cv2
  except ImportError:self.skipTest('Native host lacks OpenCV; covered by target ARM Python3.5')
  import reference
  from gesture_classifier import GestureDebouncer
  p=GestureDebouncer()
  raw=dict(code='0101',reliable=True,reason='tracked_finger_states',states=dict(zip(('Thumb','Index','Middle','Ring'),'0101')))
  result=p.update(raw,True)
  self.assertEqual(result['status'],'CONFIRMED');self.assertEqual(result['code'],'0101')
  raw['code']='1010';self.assertEqual(p.update(raw,True)['code'],'1010')
 def test_live_config_single_frame(self):
  c=json.loads((B/'delivery/app/config/algorithm.json').read_text())
  self.assertEqual(c['gesture_confirm_frames'],1);self.assertEqual(c['calibration_stable_frames'],1)
  try:import cv2
  except ImportError:self.skipTest('Native host lacks OpenCV; covered by target ARM Python3.5')
  import reference
  from skin_detection import load_config
  from headless import HeadlessRecognizer
  p=HeadlessRecognizer(load_config(str(B/'delivery/app/config/algorithm.json')),automatic=True)
  self.assertEqual(p.pipeline.debouncer.confirm_frames,1);self.assertEqual(p.open_observer.required,1)
 def test_geometry_bit_meaning_not_demo(self):
  s=(B/'delivery/app/reference/gesture_classifier.py').read_text()
  self.assertIn("('1', 'matched_tip_reaches_calibrated_extension')",s)
  self.assertIn("('0', 'calibrated_sector_retracted')",s)
 def test_uart_identity_unchanged(self):
  import hand_bus,inspect
  s=inspect.getsource(hand_bus.verify_uart_identity)
  for x in ['serial@e0001000','uart1-emio-f18-e18-20261101','console=ttyPS1']:
   self.assertIn(x,s)

if __name__=='__main__':unittest.main(verbosity=2)
