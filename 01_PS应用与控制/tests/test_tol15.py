"""User-authorized target tolerance change, without expanding calibrated travel."""
import itertools,json,os,sys,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'));sys.path.insert(0,str(B/'tests'))
from test_final import FakeBus,Clock
from hand_final import DirectDrive,DriveFault,ARRIVAL_TOLERANCE_RAW
from hand_endpoints import IDS,OPEN,CLOSED,LIMITS,FEEDBACK_MARGIN_RAW,targets

class ToleranceTests(unittest.TestCase):
 def setup_drive(self,seed=None):
  bus=FakeBus();c=Clock();events=[]
  if seed:
   bus.pos.update(seed)
   for i in IDS:bus.reg[i][42]=bus.pos[i]
  d=DirectDrive(bus,lambda n,**k:events.append((n,k)),clock=c,sleep=lambda x:None)
  d.release();d.prepare();d.arm(lambda:OPEN);bus.instant=False
  return bus,d,c,events
 def test_exact_constant_and_safety_margin_are_separate(self):
  self.assertEqual(ARRIVAL_TOLERANCE_RAW,15);self.assertEqual(FEEDBACK_MARGIN_RAW,15)
 def test_reported_id4_608_vs602_no_longer_no_progress_fault(self):
  b,d,c,e=self.setup_drive({4:628});d.move_latest(lambda:OPEN)
  b.pos[4]=608;c.advance(.850589909);d.monitor(4)
  self.assertIn(4,d.motion)
  c.advance(.21);d.monitor(4);self.assertNotIn(4,d.motion)
  reached=next(v for n,v in e if n=='ENDPOINT_REACHED' and v['sid']==4)
  self.assertEqual(reached['target_raw'],602);self.assertEqual(reached['error_raw'],6)
  self.assertEqual(reached['arrival_tolerance_raw'],15)
 def test_plus_and_minus_15_inclusive_on_internal_target(self):
  # Internal position is used only to exercise both mathematical signs without
  # conflating target tracking tolerance with the separate endpoint travel limit.
  for error in [-15,15]:
   b,d,c,e=self.setup_drive({2:450})
   values=dict(d.commanded);values[2]=500;d.move_latest(lambda:values)
   b.pos[2]=500+error;d.monitor(2);c.advance(.21);d.monitor(2)
   self.assertNotIn(2,d.motion)
   d.monitor(2)  # Stationary uses the same +/-15 tolerance.
 def test_all_16_codes_each_servo_arrival_15_inside_calibrated_range(self):
  for bits in itertools.product('01',repeat=4):
   goal=targets(''.join(bits));b,d,c,e=self.setup_drive();d.move_latest(lambda:goal)
   for sid in IDS:
    lo,hi=LIMITS[sid];b.pos[sid]=goal[sid]+(15 if goal[sid]==lo else -15)
    d.monitor(sid)
   c.advance(.21)
   for sid in IDS:d.monitor(sid)
   self.assertEqual(d.motion,{})
 def test_stationary_16_still_faults_with_signed_error(self):
  for error in [-16,16]:
   b,d,c,e=self.setup_drive({2:450});values=dict(d.commanded);values[2]=500
   d.move_latest(lambda:values);b.pos[2]=500;d.monitor(2);c.advance(.21);d.monitor(2)
   b.pos[2]=500+error
   with self.assertRaises(DriveFault) as cm:d.monitor(2)
   self.assertIn('Stationary position drift',str(cm.exception))
   self.assertEqual(cm.exception.details['error_raw'],error)
   self.assertEqual(cm.exception.details['arrival_tolerance_raw'],15)
 def test_outside_15_still_has_no_progress_detection(self):
  b,d,c,e=self.setup_drive({4:628});d.move_latest(lambda:OPEN)
  b.pos[4]=618;d.monitor(4);c.advance(.81)
  with self.assertRaisesRegex(DriveFault,'no progress'):d.monitor(4)
 def test_short_path_does_not_reimpose_old_3raw_target_gate(self):
  b,d,c,e=self.setup_drive({2:407});d.move_latest(lambda:OPEN)
  b.pos[2]=419;d.monitor(2);c.advance(.21);d.monitor(2)
  self.assertNotIn(2,d.motion)
 def test_calibrated_envelope_still_limits_outward_overshoot(self):
  b,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN)
  b.pos[4]=586 # Below calibrated minimum602 minus authorized15raw margin.
  with self.assertRaises(DriveFault) as cm:d.monitor(4)
  self.assertIn('outside',str(cm.exception));self.assertEqual(cm.exception.details['measured_raw'],586)
 def test_arm_seed_motion_guard_stays_3(self):
  b=FakeBus();d=DirectDrive(b,lambda *a,**k:None,sleep=lambda x:None)
  d.release();d.prepare()
  def shift(sid,value):b.pos[sid]=value+4
  b.on_goal=shift
  with self.assertRaisesRegex(RuntimeError,'Movement during current-position ARM'):d.arm(lambda:OPEN)
  d.release();self.assertFalse(b.enabled)
 def test_same_target_is_not_resent_for_6raw_error(self):
  b,d,c,e=self.setup_drive({4:628});d.move_latest(lambda:OPEN)
  # Keep other servos at their targets to isolate ID4's measured 6raw offset.
  for i in IDS:b.pos[i]=OPEN[i]
  b.pos[4]=608;count=len(b.calls);d.move_latest(lambda:OPEN);c.advance(.21);d.move_latest(lambda:OPEN)
  self.assertEqual(len(b.calls),count);self.assertEqual(d.commanded[4],602)
 def test_new_target_does_not_wait_for_arrival(self):
  b,d,c,e=self.setup_drive();d.move_latest(lambda:OPEN);c.advance(.001)
  d.move_latest(lambda:CLOSED);self.assertEqual(d.commanded,CLOSED)
 def test_in_band_instability_still_has_total_deadline(self):
  b,d,c,e=self.setup_drive({2:407});d.move_latest(lambda:OPEN)
  for n in range(20):
   c.advance(.1);b.pos[2]=404 if n%2 else 419;d.monitor(2)
  c.advance(.2)
  with self.assertRaisesRegex(DriveFault,'total timeout'):d.monitor(2)

if __name__=='__main__':unittest.main(verbosity=2)
