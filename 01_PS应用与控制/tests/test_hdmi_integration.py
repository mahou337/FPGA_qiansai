import sys,os,time,threading,unittest,tempfile,json
from pathlib import Path
from unittest import mock
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
try:
    import numpy as np
except ImportError:
    raise unittest.SkipTest('NumPy absent in host Python; run all display tests under ARM Python3.5')
import run
from mask_display import MaskDisplay,DeviceBackend

class Backend(object):
    def __init__(self): self.data=[];self.closed=False
    def write(self,b): self.data.append(b)
    def status(self): return (0x4d534b31,1,0x00f00140,76800,0,0,0,0)
    def close(self): self.closed=True

class HDMIIntegration(unittest.TestCase):
    def test_defaults_and_hz_bounds(self):
        a=run.parser().parse_args(['--hardware'])
        self.assertFalse(a.hdmi);self.assertFalse(a.hand);self.assertEqual(a.hdmi_hz,5)
        for hz in ('0','-1','5.1','nan','inf'):
            with self.assertRaises(SystemExit) as e: run.main(['--hardware','--hdmi-hz',hz])
            self.assertEqual(e.exception.code,2)
    def test_thread_start_failure_isolated(self):
        with mock.patch('threading.Thread.start',side_effect=RuntimeError('thread injected')):
            d=MaskDisplay(True)
        self.assertFalse(d.enabled);self.assertIn('thread injected',d.error)
        self.assertFalse(d.close()['worker_alive'])
    def test_missing_device_isolated(self):
        d=MaskDisplay(True,device='/nonexistent-gesture-test-device')
        d.thread.join(1)
        self.assertFalse(d.enabled);self.assertTrue(d.error);self.assertFalse(d.submit(None))
        self.assertFalse(d.close()['shutdown_unconfirmed'])
    def test_submit_exception_stops_only_display(self):
        class Bad:
            shape=(240,320);dtype='uint8'
            def tobytes(self,order):raise RuntimeError('snapshot injected')
        f=Backend();d=MaskDisplay(True,_backend_factory=lambda:f)
        self.assertFalse(d.submit(Bad()));d.close()
        self.assertFalse(d.enabled);self.assertIn('snapshot injected',d.error);self.assertTrue(f.closed)
    def test_no_new_frame_no_extra_write(self):
        f=Backend();d=MaskDisplay(True,_backend_factory=lambda:f)
        d.submit(np.zeros((240,320),np.uint8));time.sleep(.3)
        self.assertEqual(len(f.data),1);time.sleep(.3);self.assertEqual(len(f.data),1)
        d.close();self.assertTrue(f.closed)
    def test_bounded_close_reports_pending(self):
        gate=threading.Event();started=threading.Event();f=Backend()
        def slow(b):started.set();gate.wait(3)
        f.write=slow;d=MaskDisplay(True,_backend_factory=lambda:f)
        d.submit(np.zeros((240,320),np.uint8));self.assertTrue(started.wait(1))
        try:
            t=time.monotonic();s=d.close()
            self.assertLess(time.monotonic()-t,.8);self.assertTrue(s['shutdown_unconfirmed'])
        finally:gate.set();d.thread.join(2)
        self.assertTrue(f.closed)
    def test_device_short_write_and_identity_closes_fd(self):
        with mock.patch('os.open',return_value=123),mock.patch('os.close') as close:
            with mock.patch.object(DeviceBackend,'status',return_value=(0,0,0,0)):
                with self.assertRaises(RuntimeError):DeviceBackend('fake')
            close.assert_called_once_with(123)
        b=object.__new__(DeviceBackend);b.fd=123
        with mock.patch('os.write',return_value=1):
            with self.assertRaises(IOError): b.write(bytes(76800))
    def test_run_real_mask_and_cleanup_independent_no_images(self):
        # Actual run.main replay loop and actual recognizer; no UART or hardware.
        with tempfile.TemporaryDirectory() as td:
            import cv2
            images=Path(td)/'input';images.mkdir()
            a=np.zeros((480,640,3),np.uint8)
            cv2.rectangle(a,(180,130),(420,400),(80,120,180),-1)
            cv2.imwrite(str(images/'real-01.png'),a)
            seen=[];actual=[];summary=[]
            process=run.HeadlessRecognizer.process
            def wrapped(obj,frame):
                result,masks,timing=process(obj,frame)
                m=masks['final_hand_mask'];actual.append(m)
                self.assertEqual(m.shape,(240,320));self.assertEqual(m.dtype,np.uint8)
                self.assertTrue(set(np.unique(m)).issubset({0,255}))
                return result,masks,timing
            class Display:
                enabled=True
                def __init__(self,enabled,hz):self.enabled=enabled
                def submit(self,m):seen.append(m);return True
                def close(self):summary.append(True);return {'test_backend':True}
            with mock.patch.object(run,'MaskDisplay',Display),mock.patch.object(run.HeadlessRecognizer,'process',wrapped):
                rc=run.main(['--images',str(images),'--replay-output',str(Path(td)/'out'),'--automatic','--no-input','--no-images','--hdmi'])
            self.assertEqual(rc,0);self.assertEqual(len(actual),1);self.assertIs(seen[0],actual[0]);self.assertEqual(summary,[True])
    def test_snapshot_is_independent_of_later_process(self):
        cfg=run.load_config(str(B/'delivery/app/config/algorithm.json'))
        recog=run.HeadlessRecognizer(cfg,automatic=True,edge_assist=True,lowtip_tracking=True)
        frame=np.zeros((240,320,3),np.uint8)
        _,m,_=recog.process(frame);first=m['final_hand_mask'];before=first.tobytes()
        _,m2,_=recog.process(frame)
        self.assertIsNot(first,m2['final_hand_mask']);self.assertEqual(first.tobytes(),before)
if __name__=='__main__':unittest.main()
