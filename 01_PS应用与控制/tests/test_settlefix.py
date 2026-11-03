"""Reproduce the board start/target facts; post-fault raw=408 is synthetic.
The actual failing feedback was NOT recorded by the previous release.
No test below opens a physical UART or enables real hardware.
"""
import importlib.util,io,json,os,sys,time,unittest
from pathlib import Path
from unittest import mock
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'));sys.path.insert(0,str(B/'tests'))
from test_final import FakeBus,Clock
import test_final
from hand_final import DirectDrive,DriveFault,SETTLE_FEEDBACK_SECONDS
from hand_endpoints import IDS,OPEN,CLOSED,targets

SEED={1:558,2:407,3:418,4:628,5:442,6:611,7:321,8:671}

class MotionStateRegression(unittest.TestCase):
 def setup_drive(self,cls=DirectDrive):
  bus=FakeBus();clock=Clock();clock.t=150.428780691;events=[]
  bus.pos=dict(SEED)
  for i in IDS:bus.reg[i][42]=bus.pos[i]
  d=cls(bus,lambda name,**kw:events.append((name,kw)),clock=clock,sleep=lambda unused:None)
  d.release();d.prepare();d.arm(lambda:OPEN);bus.instant=False
  return bus,d,clock,events
 def test_previous_driver_reproduces_small_target_bug(self):
  spec=importlib.util.spec_from_file_location('old_drive',str(B/'tests/fixtures/previous_hand_final.py'))
  old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
  bus,d,c,e=self.setup_drive(old.DirectDrive);d.move_latest(lambda:OPEN)
  self.assertNotIn(2,d.motion)
  bus.pos[2]=408;c.advance(.122733570)
  with self.assertRaisesRegex(RuntimeError,'Stationary position drift id=2'):d.monitor(2)
 def test_407_to_404_transient_408_stays_motion_then_settles(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  self.assertIn(2,d.motion)
  bus.pos[2]=408;c.advance(.122733570);d.monitor(2)
  self.assertIn(2,d.motion)
  bus.pos[2]=406;c.advance(.05);d.monitor(2)
  bus.pos[2]=404;c.advance(.05);d.monitor(2)
  self.assertIn(2,d.motion)
  c.advance(.21);d.monitor(2);self.assertNotIn(2,d.motion)
  self.assertTrue(any(n=='ENDPOINT_REACHED' and v['sid']==2 for n,v in e))
 def test_every_small_changed_goal_gets_motion_state(self):
  for gap in [0,1,2,3]:
   bus,d,c,e=self.setup_drive()
   bus.pos[2]=404+gap
   d.move_latest(lambda:OPEN)
   self.assertEqual(d.commanded[2],404);self.assertIn(2,d.motion)
 def test_large_goal_first_in_band_sample_is_not_stationary(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  bus.pos[7]=OPEN[7];c.advance(.1);d.monitor(7)
  self.assertIn(7,d.motion)
  c.advance(.21);d.monitor(7);self.assertNotIn(7,d.motion)
 def test_new_target_does_not_wait_for_settle_interval(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  c.advance(.001);d.move_latest(lambda:CLOSED)
  self.assertEqual(d.commanded,CLOSED)
  self.assertLess(c.t-150.428780691,SETTLE_FEEDBACK_SECONDS)
 def test_same_target_no_resend_during_settle(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN);count=len(bus.calls)
  c.advance(.03);d.move_latest(lambda:OPEN)
  self.assertEqual(len(bus.calls),count)
 def test_new_target_restarts_settle_not_stall_timer(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  bus.pos[2]=404;c.advance(.1);d.monitor(2)
  self.assertIsNotNone(d.motion[2]['quiet_since'])
  p=d.motion[2]['progress_at'];d.move_latest(lambda:CLOSED)
  self.assertIsNone(d.motion[2]['quiet_since']);self.assertEqual(d.motion[2]['progress_at'],p)
 def test_persistent_error_outside_arrival_band_still_faults(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  bus.pos[4]=618;d.monitor(4);c.advance(.81)
  with self.assertRaises(DriveFault) as cm:d.monitor(4)
  self.assertIn('no progress',str(cm.exception))
  self.assertEqual(cm.exception.details['measured_raw'],618)
  self.assertEqual(cm.exception.details['target_raw'],602)
  self.assertEqual(cm.exception.details['error_raw'],16)
 def test_settled_position_drift_still_faults(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  bus.pos[2]=404;d.monitor(2);c.advance(.21);d.monitor(2)
  bus.pos[2]=420
  with self.assertRaisesRegex(DriveFault,'Stationary position drift'):d.monitor(2)
 def test_small_goal_path_includes_arrival_band_but_remains_bounded(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN);bus.pos[2]=438
  with self.assertRaises(DriveFault) as cm:d.monitor(2)
  self.assertIn('commanded path',str(cm.exception))
  self.assertEqual(cm.exception.details['path_raw'],[389,437])
 def test_servo_endpoint_envelope_not_relaxed(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN);bus.pos[2]=388
  with self.assertRaises(DriveFault) as cm:d.monitor(2)
  self.assertEqual(cm.exception.details['measured_raw'],388)
 def test_unsettled_in_band_oscillation_has_total_deadline(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  for j in range(20):
   c.advance(.1);bus.pos[2]=404 if j%2 else 407;d.monitor(2)
  c.advance(.2)
  with self.assertRaisesRegex(DriveFault,'total timeout'):d.monitor(2)
 def test_quiet_span_resets_after_out_of_band_sample(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  bus.pos[4]=602;d.monitor(4);c.advance(.15);bus.pos[4]=618;d.monitor(4)
  self.assertIsNone(d.motion[4]['quiet_since'])
  bus.pos[4]=602;c.advance(.01);d.monitor(4);c.advance(.15);d.monitor(4)
  self.assertIn(4,d.motion)
 def test_fault_snapshot_preserves_pre_release_evidence(self):
  bus,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN);bus.pos[4]=618;d.monitor(4);c.advance(.81)
  with self.assertRaises(DriveFault):d.monitor(4)
  snapshot=d.fault_snapshot();d.release()
  self.assertEqual(snapshot['commanded_raw'][4],602)
  self.assertEqual(snapshot['last_feedback'][4]['raw'],618)
  self.assertTrue(all(v==1 for v in snapshot['torque_expected'].values()))
  self.assertFalse(bus.enabled)

@unittest.skipUnless(os.name=='posix','POSIX bridge')
class BridgeExitTests(unittest.TestCase):
 def bridge(self,payload,rc=1):
  from hand_bridge import HandBridge
  b=HandBridge.__new__(HandBridge)
  b.release_verified=False;b.exit_status=None;b.exit_collected=False;b.errors=None
  b.child=mock.Mock();b.child.returncode=rc;b.child.poll.return_value=rc
  b.child.stdin=None;b.child.stdout=io.BytesIO(payload)
  return b
 def ack(self,verified=True,rc=1):
  return (json.dumps(dict(kind='HAND_EXIT',return_code=rc,release_verified=verified,error='Stationary position drift id=2'))+'\n').encode()
 def test_fault_ack_does_not_become_release_failure(self):
  b=self.bridge(self.ack());self.assertEqual(b.close(),1);self.assertTrue(b.release_verified)
 def test_missing_ack_never_claims_release(self):
  b=self.bridge(b'');b.close();self.assertFalse(b.release_verified)
 def test_false_ack_requires_power_cut(self):
  b=self.bridge(self.ack(False));b.close();self.assertFalse(b.release_verified)
 def test_bad_or_mismatched_ack_not_trusted(self):
  for data in [b'garbage\n',self.ack(True,0),b'{"kind":"HAND_EXIT","return_code":1,"release_verified":"true"}\n']:
   b=self.bridge(data);b.close();self.assertFalse(b.release_verified)
 def test_oversize_ack_not_trusted(self):
  b=self.bridge(b' '*4097+self.ack());b.close();self.assertFalse(b.release_verified)
 def test_submit_exposes_actual_fault_and_verified_release(self):
  b=self.bridge(self.ack())
  with self.assertRaises(RuntimeError) as cm:b.submit(b'',0)
  self.assertIn('Stationary position drift id=2',str(cm.exception))
  self.assertIn('torque-off verified',str(cm.exception))
  b.close();self.assertTrue(b.release_verified)
 def test_signalled_without_ack_is_unconfirmed(self):
  b=self.bridge(b'',-9);b.close();self.assertFalse(b.release_verified)

@unittest.skipUnless(os.name=='posix','POSIX worker')
class WorkerAckTests(unittest.TestCase):
 def scenario(self,mode):
  bus,rc,events,before=test_final.WorkerTests().scenario(mode)
  acks=[json.loads(s) for s in bus.worker_stdout.splitlines() if s.startswith('{')]
  ack=next(a for a in acks if a.get('kind')=='HAND_EXIT')
  return bus,rc,events,ack
 def test_fault_exit_with_verified_release(self):
  b,rc,e,a=self.scenario('goal_failure');self.assertEqual(rc,1)
  self.assertTrue(a['release_verified']);self.assertEqual(a['return_code'],1)
  self.assertIn('UART write fault',a['error'])
  fault=next(x for x in e if x['event']=='FAULT')
  self.assertIn('last_feedback',fault['diagnostics'])
 def test_release_failure_ack_false(self):
  b,rc,e,a=self.scenario('release_failure');self.assertEqual(rc,1)
  self.assertFalse(a['release_verified'])
 def test_normal_exit_ack_true(self):
  b,rc,e,a=self.scenario('eof');self.assertEqual(rc,0);self.assertTrue(a['release_verified'])
 def test_signal_exit_ack_true(self):
  b,rc,e,a=self.scenario('signal');self.assertEqual(rc,0);self.assertTrue(a['release_verified'])

class ScopeTests(unittest.TestCase):
 def test_unchanged_files_identical_to_previous(self):
  import hashlib
  previous=json.loads((B/'validation/PREVIOUS_RELEASE_HASHES.json').read_text())
  changed={'app/ps/run.py','README.md','SHA256SUMS','ACTIVE_ENDPOINTS.json','app/ps/hand_endpoints.py','app/ps/hand_final.py','app/ps/hand_worker.py'}
  for name in sorted(set(previous)-changed):
   self.assertEqual(hashlib.sha256((B/'delivery'/name).read_bytes()).hexdigest(),previous[name])

if __name__=='__main__':unittest.main(verbosity=2)
