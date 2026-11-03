import os,sys,time,tempfile,unittest,io,contextlib
from pathlib import Path
from unittest import mock
B=Path(__file__).resolve().parents[1];sys.path.insert(0,str(B/'delivery/app/ps'))
try:
 import cv2,numpy as np
 HAVE_CV=True
except ImportError:HAVE_CV=False

@unittest.skipUnless(HAVE_CV,'Runtime needs OpenCV; tested on target ARM Python3.5')
class RuntimeTests(unittest.TestCase):
 def scenario(self,verified=True,bridge_rc=0):
  import run
  order=[];packets=[];reset=[]
  class Store:
   def __init__(self,*a):self.directory=Path('/tmp/simulated')
   def metadata(self,*a):pass
   def event(self,*a):pass
   def packet(self,p):order.append(('store',p))
   def record(self,*a):pass
   def cycle(self,*a):pass
   def summary(self,*a):pass
   def close(self):pass
  class Terminal:
   def __init__(self,*a):pass
   def commands(self):return []
   def close(self):pass
  class Bridge:
   def __init__(self,*a):self.release_verified=verified
   def submit(self,p,captured):packets.append(run.decode(p));order.append(('bridge',p))
   def close(self):return bridge_rc
  class HW:
   def __init__(self,*a):self.n=0
   def read(self,*a):return 0
   def camera_read(self,addr):return .0 if addr==0x503d else 0x20
   def camera_write(self,*a):pass
   def initialize(self,*a):pass
   def capture(self,*a):self.n+=1;return self.n,np.zeros((480,640,3),np.uint8)
   def diagnostics(self):return {}
   def close(self):pass
  class Rec:
   def __init__(self,*a,**kw):
    self.background=mock.Mock();self.background.samples=None
    self.background.last_info={'effective':True}
   def reset(self,reason):reset.append(reason)
   def process(self,frame):
    time.sleep(.8)
    return dict(status='CONFIRMED',raw={'code':'0101'},code='0101',reliable=True),{},{}
  # Camera register must be integer (actual hardware semantics).
  HW.camera_read=lambda self,addr:0 if addr==0x503d else 0x20
  with mock.patch.object(run,'RunStore',Store),mock.patch.object(run,'ForegroundTerminal',Terminal),mock.patch.object(run,'HeadlessRecognizer',Rec),mock.patch('hand_bridge.HandBridge',Bridge),mock.patch('hardware_vga.HardwareVGA',HW),mock.patch.object(run,'validate_diag'),mock.patch.object(os,'geteuid',return_value=0),mock.patch.object(run.platform,'release',return_value='4.19.0-xilinx-v2019.1'):
   rc=run.main(['--hardware','--automatic','--hand','--no-images','--no-input','--frames','2'])
  self.assertEqual(rc,0 if verified and not bridge_rc else 1)
  self.assertEqual(len([p for p in packets if p['raw']=='0101' and p['valid']]),2)
  self.assertFalse(any(p['status']=='STALE' for p in packets));self.assertEqual(reset,[])
  for i,(kind,p) in enumerate(order):
   if kind=='store' and run.decode(p)['status']!='PENDING':self.assertEqual(order[i-1],('bridge',p))

 def test_slow_complete_frames_reach_bridge_before_store_without_stale(self):
  self.scenario()
 def test_main_distinguishes_fault_from_release_failure(self):
  err=io.StringIO()
  with contextlib.redirect_stderr(err):self.scenario(True,1)
  self.assertIn('HAND_FAULT_RELEASE_VERIFIED',err.getvalue())
  self.assertNotIn('HAND_RELEASE_NOT_CONFIRMED',err.getvalue())
 def test_main_keeps_power_cut_warning_without_ack(self):
  err=io.StringIO()
  with contextlib.redirect_stderr(err):self.scenario(False,0)
  self.assertIn('HAND_RELEASE_NOT_CONFIRMED',err.getvalue())
