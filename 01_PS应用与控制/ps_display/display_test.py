"""DISPLAY-ONLY board test. Does not import recognizer or any UART/servo code."""
from __future__ import print_function
import argparse
import time
import sys
import numpy as np
from mask_display import DeviceBackend, MaskDisplay
p=argparse.ArgumentParser()
p.add_argument('--mode',choices=['pattern','mask'],required=True)
p.add_argument('--seconds',type=float,default=20)
a=p.parse_args()
if a.mode=='pattern':
    b=DeviceBackend('/dev/gesture-mask-display')
    try:
        # Test utility only: wait out initial queued blank. Recognition never does this.
        time.sleep(.05);b.mode(2);time.sleep(a.seconds);print(b.status())
    finally:b.close()
else:
    yy,xx=np.indices((240,320))
    mask=np.where(((xx//17+yy//13)%2)!=0,255,0).astype(np.uint8)
    mask[:12,:12]=255;mask[-12:,-12:]=0
    d=MaskDisplay(True)
    try:
        t=time.monotonic()
        while time.monotonic()-t<a.seconds:
            d.submit(mask);time.sleep(.2)
        print(d.stats())
    finally:
        final_stats=d.close()
        print(final_stats)
    if final_stats['error'] or not final_stats['written']:
        sys.exit('FAIL: no successful mask upload or display worker error; see statistics')
