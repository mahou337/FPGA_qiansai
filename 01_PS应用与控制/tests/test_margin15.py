import itertools,sys,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import IDS,OPEN,CLOSED,LIMITS,targets,check_raw,health
from hand_bus import raw_angle
from hand_final import DriveFault
import test_tol15

class Margin15Regression(unittest.TestCase):
 def drive(self,seed=None):return test_tol15.ToleranceTests().setup_drive(seed)
 def test_reported_id5_443_target439_accepted_and_settles(self):
  b,d,c,e=self.drive({5:442});d.move_latest(lambda:OPEN)
  b.pos[5]=443;b.health[5].update(temperature=16,voltage=7.3,load_raw=45)
  d.monitor(5);c.advance(.21);d.monitor(5);self.assertNotIn(5,d.motion)
  d.monitor(5);self.assertEqual(d.commanded[5],439)
 def test_seed_within_new_margin_is_accepted_without_zeroing(self):
  b,d,c,e=self.drive({5:443});self.assertEqual(d.commanded[5],443)
  d.move_latest(lambda:OPEN);self.assertEqual(d.commanded[5],439)
 def test_every_gesture_every_servo_outward_15_settles(self):
  for bits in itertools.product('01',repeat=4):
   goal=targets(''.join(bits));b,d,c,e=self.drive();d.move_latest(lambda:goal)
   for i in IDS:
    lo,hi=LIMITS[i];b.pos[i]=goal[i]+(-15 if goal[i]==lo else 15);d.monitor(i)
   c.advance(.21)
   for i in IDS:d.monitor(i)
   self.assertEqual(d.motion,{})
 def test_both_global_edges_inclusive_15_reject_16(self):
  for i in IDS:
   lo,hi=LIMITS[i]
   for raw in [lo-15,hi+15]:check_raw(i,raw,True)
   for raw in [lo-16,hi+16]:
    with self.assertRaises(RuntimeError):check_raw(i,raw,True)
 def test_feedback_margin_does_not_authorize_outside_goals(self):
  for i in IDS:
   lo,hi=LIMITS[i]
   for raw in [lo-1,lo-15,hi+1,hi+15]:
    with self.assertRaises(RuntimeError):check_raw(i,raw,False)
 def test_path_start_30_is_allowed_but_31_faults(self):
  b,d,c,e=self.drive({1:538});d.move_latest(lambda:OPEN)
  for raw in [534,523,508]:b.pos[1]=raw;d.monitor(1)
  b.pos[1]=507
  with self.assertRaisesRegex(DriveFault,'outside commanded path'):d.monitor(1)
 def test_id5_outward_16_still_faults(self):
  b,d,c,e=self.drive();d.move_latest(lambda:OPEN);b.pos[5]=455
  with self.assertRaisesRegex(DriveFault,'outside'):d.monitor(5)
 def test_load750_remains_fault_and_release_verified(self):
  b,d,c,e=self.drive();b.health[7].update(load_raw=750,temperature=15,voltage=6.5)
  with self.assertRaisesRegex(DriveFault,'temperature/load'):d.monitor(7)
  d.release();self.assertFalse(b.enabled)
if __name__=='__main__':unittest.main(verbosity=2)
