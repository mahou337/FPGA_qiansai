import sys,json,hashlib,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import OPEN,CLOSED,LIMITS,FEEDBACK_MARGIN_RAW,SPEED_RADIANS,VOLTAGE_WINDOW
from hand_final import PATH_MARGIN_RAW,ARRIVAL_TOLERANCE_RAW,DriveFault
import test_tol15
import test_final

class ThumbPathTests(unittest.TestCase):
 def drive(self,seed=None):return test_tol15.ToleranceTests().setup_drive(seed)
 def test_thumb_increment_direction_and_quantization(self):
  self.assertEqual(round(20*1024/300),68)
  self.assertEqual(CLOSED[7],263-68);self.assertEqual(CLOSED[8],796+68)
  self.assertEqual(68*300/1024,19.921875)
  self.assertEqual((OPEN[7],OPEN[8]),(440,582))
  self.assertEqual([CLOSED[i] for i in range(1,7)],[206,769,90,989,128,895])
 def test_reported_id3_189_to418_feedback168_now_inside(self):
  b,d,c,e=self.drive({3:189});d.move_latest(lambda:OPEN)
  b.pos[3]=168;b.health[3].update(temperature=20,voltage=6.5,load_raw=585)
  d.monitor(3);self.assertIn(3,d.motion);self.assertEqual(d.commanded[3],418)
  # Passing this sample does not certify completion or waive stall detection.
  c.advance(.81)
  with self.assertRaisesRegex(DriveFault,'no progress'):d.monitor(3)
 def test_path30_boundary_and31_fault(self):
  b,d,c,e=self.drive({3:189});d.move_latest(lambda:OPEN)
  b.pos[3]=159;d.monitor(3);b.pos[3]=158
  with self.assertRaises(DriveFault) as cm:d.monitor(3)
  self.assertIn('outside commanded path',str(cm.exception))
  self.assertEqual(cm.exception.details['path_raw'],[159,433]);self.assertEqual(cm.exception.details['path_margin_raw'],30)
 def test_global15_still_overrides_path30(self):
  b,d,c,e=self.drive({3:189});d.move_latest(lambda:OPEN);b.pos[3]=434
  with self.assertRaisesRegex(DriveFault,'outside 90..418 margin=15'):d.monitor(3)
 def test_thumb_new_targets_and_new_limits(self):
  self.assertEqual(LIMITS[7],(195,440));self.assertEqual(LIMITS[8],(582,864))
  b,d,c,e=self.drive({7:263,8:796});d.move_latest(lambda:CLOSED)
  self.assertEqual(d.commanded[7],195);self.assertEqual(d.commanded[8],864)
  for i in [7,8]:b.pos[i]=CLOSED[i];d.monitor(i)
  c.advance(.21)
  for i in [7,8]:d.monitor(i);self.assertNotIn(i,d.motion)
 def test_adjustment_provenance_not_new_measurement(self):
  a=json.loads((B/'delivery/ACTIVE_ENDPOINTS.json').read_text());p=B/'delivery'/a['adjustment_record'];r=json.loads(p.read_text())
  self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),a['adjustment_sha256'])
  self.assertTrue(r['derived_not_newly_measured']);self.assertFalse(r['physical_loaded_motion_verified'])
  self.assertEqual(a['derived_adjustments_raw'],{'7':-68,'8':68})
 def test_policy_reports_separate_margins_and_settings(self):
  self.assertEqual(PATH_MARGIN_RAW,30);self.assertEqual(FEEDBACK_MARGIN_RAW,15);self.assertEqual(ARRIVAL_TOLERANCE_RAW,15)
  self.assertEqual(SPEED_RADIANS,5);self.assertEqual(VOLTAGE_WINDOW,(4.5,7.6))
  b,rc,events,before=test_final.WorkerTests().scenario('eof')
  p=next(x for x in events if x['event']=='CONTROL_POLICY')
  self.assertEqual(p['path_margin_raw'],30);self.assertEqual(p['feedback_margin_raw'],15)
if __name__=='__main__':unittest.main(verbosity=2)
