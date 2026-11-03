import sys,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import IDS,OPEN,VOLTAGE_WINDOW,health
from hand_bus import raw_angle
from hand_final import DriveFault
import test_tol15
import test_final

class Voltage76Tests(unittest.TestCase):
 def value(self,i,v):return dict(raw=OPEN[i],angle=raw_angle(OPEN[i]),voltage=v,temperature=17,load_raw=0)
 def test_all_eight_inclusive_window(self):
  self.assertEqual(VOLTAGE_WINDOW,(4.5,7.6))
  for i in IDS:
   for v in [4.5,7.5,7.6]:health({i:self.value(i,v)})
 def test_outside_and_nonfinite_rejected(self):
  for i in IDS:
   for v in [4.4,4.4999,7.6001,7.7,float('nan'),float('inf'),float('-inf')]:
    with self.assertRaisesRegex(RuntimeError,'voltage outside 4.5..7.6V'):health({i:self.value(i,v)})
 def test_reported_id2_405_target404_voltage76_passes(self):
  b,d,c,e=test_tol15.ToleranceTests().setup_drive({2:407});d.move_latest(lambda:OPEN)
  b.pos[2]=405;b.health[2].update(voltage=7.6,temperature=17,load_raw=0)
  d.monitor(2);c.advance(.21);d.monitor(2);d.monitor(2)
  self.assertNotIn(2,d.motion);self.assertEqual(d.commanded[2],404)
 def test_77_fault_still_releases(self):
  b,d,c,e=test_tol15.ToleranceTests().setup_drive();b.health[2]['voltage']=7.7
  with self.assertRaisesRegex(DriveFault,'voltage outside 4.5..7.6V'):d.monitor(2)
  d.release();self.assertFalse(b.enabled)
 def test_policy_log_matches_enforced_window(self):
  b,rc,events,before=test_final.WorkerTests().scenario('eof')
  self.assertEqual(next(x for x in events if x['event']=='CONTROL_POLICY')['voltage_window'],[4.5,7.6])
if __name__=='__main__':unittest.main(verbosity=2)
