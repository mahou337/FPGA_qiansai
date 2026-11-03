"""Offline behavioral tests, NOT ARM recognition-performance measurements."""
import errno
import threading
import time
import unittest
try:
    import numpy as np
except ImportError:
    raise unittest.SkipTest('NumPy absent in host Python; run all display tests under ARM Python3.5')
from mask_display import MaskDisplay

class Fake(object):
    def __init__(self, delay=0, fail=False):
        self.data=[]; self.delay=delay; self.fail=fail; self.closed=False
        self.started=threading.Event()
    def write(self, data):
        self.started.set()
        if self.fail: raise OSError(errno.EIO,'injected')
        time.sleep(self.delay)
        self.data.append(data)
    def status(self):return (0x4d534b31,1,0x00f00140,76800,0,0,0,0)
    def close(self):self.closed=True

class Tests(unittest.TestCase):
    def test_snapshot_rate_and_type(self):
        f=Fake(.1); d=MaskDisplay(True,_backend_factory=lambda:f)
        a=np.zeros((240,320),dtype=np.uint8)
        self.assertTrue(d.submit(a));a[:]=255
        self.assertFalse(d.submit(a));time.sleep(.15)
        self.assertEqual(f.data,[bytes(76800)])
        d.next_submit=0
        self.assertFalse(d.submit(a.astype(np.float32)))
        self.assertEqual(d.counts['invalid'],1)
        d.close();self.assertTrue(f.closed)
    def test_latest_slot_nonblocking_and_strided(self):
        f=Fake(.35);d=MaskDisplay(True,_backend_factory=lambda:f)
        a=np.zeros((240,640),dtype=np.uint8)[:,::2]
        d.submit(a);self.assertTrue(f.started.wait(1))
        for val in (1,2,255):
            a[:]=val;d.next_submit=0
            t=time.monotonic();self.assertTrue(d.submit(a))
            self.assertLess(time.monotonic()-t,.1) # catches waiting for .35s IO
        time.sleep(.75);d.close()
        self.assertEqual(len(f.data),2);self.assertEqual(f.data[-1],bytes([255])*76800)
        self.assertEqual(d.counts['replaced'],2)
    def test_exception_and_disabled(self):
        f=Fake(fail=True);d=MaskDisplay(True,_backend_factory=lambda:f)
        a=np.zeros((240,320),dtype=np.uint8);d.submit(a);time.sleep(.05)
        self.assertFalse(d.enabled);self.assertIn('injected',d.error)
        self.assertFalse(d.submit(a));d.close()
        off=MaskDisplay(False,_backend_factory=lambda:1/0)
        self.assertFalse(off.submit(a));off.close()
    def test_busy_drop_and_lock_contention(self):
        f=Fake()
        def busy(data):raise OSError(errno.EAGAIN,'busy')
        f.write=busy;d=MaskDisplay(True,_backend_factory=lambda:f)
        a=np.zeros((240,320),dtype=np.uint8)
        d.lock.acquire()
        try:self.assertFalse(d.submit(a))
        finally:d.lock.release()
        d.next_submit=0;d.submit(a);time.sleep(.05)
        self.assertEqual(d.counts['busy_drops'],1);self.assertTrue(d.enabled)
        d.close()
if __name__=='__main__':unittest.main()
