"""Real-recognizer replay adapter, no camera or UART operations in this script.
The user-supplied factory must create ONLY the actual recognizer, with fixed config.
Run off/on in separate processes with the same NPY input and factory configuration.
"""
from __future__ import print_function
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from mask_display import MaskDisplay, percentile
p=argparse.ArgumentParser()
p.add_argument('--factory',required=True,help='module:callable returning current recognizer only')
p.add_argument('--frames',required=True,help='fixed N,H,W,3 uint8 BGR .npy at camera resolution')
p.add_argument('--output',required=True)
p.add_argument('--hdmi',action='store_true')
p.add_argument('--rounds',type=int,default=3)
p.add_argument('--warmup',type=int,default=3)
a=p.parse_args()
module,name=a.factory.split(':',1)
factory=getattr(importlib.import_module(module),name)
if a.rounds<1 or a.warmup<0:raise ValueError('rounds >=1, warmup >=0 required')
frames=np.load(a.frames,mmap_mode='r')
if frames.dtype!=np.uint8 or frames.ndim!=4 or frames.shape[1:]!=(480,640,3) or not len(frames):
    raise ValueError('expected Nx480x640x3 uint8 BGR replay; retain explicit recognizer downscale')
if frames.nbytes>64*1024*1024:raise ValueError('Replay input exceeds conservative 64MiB preload budget')
# Prefault/copy data before timing; no disk reads in the measured loop.
frames=np.array(frames,copy=True)
recognizer=factory()
for i in range(a.warmup):recognizer.process(frames[i%len(frames)].copy())
display=MaskDisplay(a.hdmi)
if a.hdmi:time.sleep(.1) # outside timed region, allows open identity checks
process_ms=[];submit_ms=[];loop_ms=[]
r0=time.process_time();start=time.monotonic()
try:
    for _ in range(a.rounds):
        for source in frames:
            frame=source.copy() # replay source ownership, same in off/on
            t=time.monotonic()
            result,masks,timing=recognizer.process(frame)
            t1=time.monotonic()
            if a.hdmi:display.submit(masks.get('final_hand_mask'))
            t2=time.monotonic()
            process_ms.append((t1-t)*1000);submit_ms.append((t2-t1)*1000);loop_ms.append((t2-t)*1000)
finally:
    elapsed=time.monotonic()-start;r1=time.process_time()
    status=display.close()
def summary(v):return dict(p50=percentile(v,.5),p95=percentile(v,.95),max=max(v) if v else None)
h=hashlib.sha256()
with open(a.frames,'rb') as f:
    for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
try:
    rss=next((int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:')),None)
except OSError:
    rss=None
report=dict(hdmi=a.hdmi,factory=a.factory,input_sha256=h.hexdigest(),frames=len(process_ms),
    elapsed_seconds=elapsed,loop_fps=len(process_ms)/elapsed,process_ms=summary(process_ms),
    submit_call_ms=summary(submit_ms),loop_ms=summary(loop_ms),display=status,
    cpu_seconds=r1-r0,
    cpu_percent=100*(r1-r0)/elapsed,
    peak_rss_kib=rss,rss_scope='Linux process VmHWM; under QEMU this is host QEMU memory, not standalone target memory',python=sys.version,numpy=np.__version__,
    camera_dma_errors=None,uart_latency=None,
    limits='replay only; camera DMA and UART require separate authorized live checks')
with open(a.output,'w') as f:json.dump(report,f,indent=2,sort_keys=True)
print(json.dumps(report,indent=2,sort_keys=True))
if a.hdmi and (status['written']==0 or status['error']):sys.exit('display inactive/error; not a valid HDMI-on performance run')
