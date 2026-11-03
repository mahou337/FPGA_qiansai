import sys,json,hashlib,itertools,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import IDS,PAIRS,OPEN,CLOSED,LIMITS,check_raw,SPEED_RADIANS,FEEDBACK_MARGIN_RAW,VOLTAGE_WINDOW,health
from hand_bus import speed_raw
from hand_final import ARRIVAL_TOLERANCE_RAW
import test_final

class NewClosedTests(unittest.TestCase):
 def test_raw_exact_and_open_preserved(self):
  self.assertEqual([OPEN[i] for i in IDS],[584,404,418,602,439,576,440,582])
  self.assertEqual([CLOSED[i] for i in IDS],[206,769,90,989,128,895,195,864])
 def test_source_hash_user_confirmation_and_unloaded_status(self):
  a=json.loads((B/'delivery/ACTIVE_ENDPOINTS.json').read_text());p=B/'delivery'/a['source_record']
  self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),a['source_sha256'])
  r=json.loads(p.read_text());self.assertTrue(r['user_confirmed_new_closed_endpoints']);self.assertFalse(a['physical_loaded_motion_verified'])
  for i in IDS:
   v=r['snapshot']['servos'][str(i)];self.assertEqual(v['raw']+a['derived_adjustments_raw'].get(str(i),0),CLOSED[i]);self.assertEqual(v['torque'],0)
   self.assertEqual(v['angle'],(v['raw']-511)*300/1024.)
 def test_limits_follow_new_endpoints_all_eight(self):
  expected=[(206,584),(404,769),(90,418),(602,989),(128,439),(576,895),(195,440),(582,864)]
  self.assertEqual([LIMITS[i] for i in IDS],expected)
  for i in IDS:
   lo,hi=LIMITS[i]
   for v in [lo,hi]:check_raw(i,v)
   for v in [lo-15,hi+15]:check_raw(i,v,True)
   for v in [lo-16,hi+16]:
    with self.assertRaises(RuntimeError):check_raw(i,v,True)
 def test_new_closed_snapshot_can_arm_without_homing(self):
  b=test_final.FakeBus();b.pos=dict(CLOSED)
  for i in IDS:b.reg[i][42]=b.pos[i]
  c=test_final.Clock();d=test_final.DirectDrive(b,lambda *a,**k:None,c,lambda _:None)
  d.release();d.prepare();d.arm(lambda:CLOSED)
  self.assertEqual([x for x in b.calls if x[0]==42],[(42,i,CLOSED[i]) for i in IDS])
  d.move_latest(lambda:OPEN);self.assertEqual(d.commanded,OPEN)
 def test_old_thumb_closed_outside_new_range_is_not_auto_homed(self):
  b,d,c,e=test_final.DriveTests().setup_drive(arm=False);b.pos[7]=107
  with self.assertRaises(RuntimeError):d.arm(lambda:OPEN)
  self.assertFalse([x for x in b.calls if x[0]==42]);self.assertFalse(b.enabled)
 def test_settings_and_all16_real_writes(self):
  self.assertEqual(SPEED_RADIANS,5.0);self.assertEqual(speed_raw(SPEED_RADIANS),977)
  self.assertEqual(FEEDBACK_MARGIN_RAW,15);self.assertEqual(ARRIVAL_TOLERANCE_RAW,15);self.assertEqual(VOLTAGE_WINDOW,(4.5,7.6))
  b,d,c,e=test_final.DriveTests().setup_drive()
  for bits in itertools.product('01',repeat=4):
   expected={i:([206,769,90,989,128,895,195,864][i-1] if bit=='0' else [584,404,418,602,439,576,440,582][i-1]) for bit,pair in zip(bits,PAIRS) for i in pair}
   d.move_latest(lambda:expected);self.assertEqual(b.pos,expected)
if __name__=='__main__':unittest.main(verbosity=2)
