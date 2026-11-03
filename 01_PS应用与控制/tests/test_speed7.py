import math,sys,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from hand_endpoints import IDS,SPEED_RADIANS,OPEN,CLOSED,FEEDBACK_MARGIN_RAW,VOLTAGE_WINDOW
from hand_bus import speed_raw,sync_packet,word,packet,SerialBus
from hand_final import DirectDrive,ARRIVAL_TOLERANCE_RAW
from test_final import Clock,FakeBus

class Speed5Tests(unittest.TestCase):
 def setup_drive(self):
  c=Clock();b=FakeBus();e=[];d=DirectDrive(b,lambda event,**kw:e.append(dict(event=event,**kw)),c,lambda _:None)
  d.release();d.prepare();return b,d,c,e
 def test_demo_conversion_and_big_endian(self):
  self.assertEqual(SPEED_RADIANS,5.0);self.assertEqual(speed_raw(SPEED_RADIANS),977)
  self.assertEqual(word(977),b'\x03\xd1');self.assertEqual(977 & (1<<15),0)
 def test_bounds_not_removed(self):
  for x in [0,-7,.099,5.001,float('inf'),float('nan')]:
   with self.assertRaises(ValueError):speed_raw(x)
  self.assertEqual(speed_raw(.25),48)
 def test_sync_packet_speed_not_clipped(self):
  f=sync_packet(46,{i:977 for i in IDS})
  self.assertEqual(f[5:7],b'\x2e\x02')
  for j,i in enumerate(IDS):self.assertEqual(f[7+3*j:10+3*j],bytes(bytearray([i,3,209])))
  self.assertEqual(sum(bytearray(f[2:])) & 255,255)
  for value in [0,978,32768]:
   with self.assertRaises(ValueError):sync_packet(46,{i:value for i in IDS})
 def test_prepare_writes_all_eight_no_torque(self):
  b,d,c,e=self.setup_drive();self.assertFalse(b.enabled)
  self.assertEqual([x for x in b.calls if x[0]==46],[(46,i,977) for i in IDS])
 def test_default_bus_speed_uses_config(self):
  frames=[];bus=SerialBus.__new__(SerialBus);bus.send=frames.append;bus.speed()
  self.assertEqual(frames,[sync_packet(46,{i:977 for i in IDS})])
 def test_fixed_speed_write_and_feedback_guard(self):
  b,d,c,e=self.setup_drive()
  with self.assertRaises(ValueError):d.write(1,46,48)
  d.arm(lambda:OPEN);b.reg[1][46]=48
  with self.assertRaisesRegex(RuntimeError,'Speed changed'):d.monitor(1)
 def test_direct_endpoint_deadline_and_event_use_speed5(self):
  b,d,c,e=self.setup_drive();d.arm(lambda:OPEN);start=dict(b.pos);d.move_latest(lambda:OPEN)
  for event in [x for x in e if x['event']=='DIRECT_ENDPOINT']:
   self.assertEqual(event['speed_raw'],977)
   self.assertAlmostEqual(event['motion_deadline_seconds'],2+2*abs(OPEN[event['sid']]-start[event['sid']])/977.)
  self.assertEqual(d.commanded,OPEN)
 def test_endpoint_tolerance_and_health_limits_unchanged(self):
  self.assertEqual(list(OPEN[i] for i in IDS),[584,404,418,602,439,576,440,582])
  self.assertEqual(list(CLOSED[i] for i in IDS),[206,769,90,989,128,895,195,864])
  self.assertEqual(ARRIVAL_TOLERANCE_RAW,15);self.assertEqual(FEEDBACK_MARGIN_RAW,15);self.assertEqual(VOLTAGE_WINDOW,(4.5,7.6))
if __name__=='__main__':unittest.main(verbosity=2)
