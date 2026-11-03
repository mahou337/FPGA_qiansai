"""Fixed historical real-frame replay. Mock display is NOT board/HDMI performance."""
import sys,json,time,hashlib,argparse,platform
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
import cv2,numpy as np
from headless import HeadlessRecognizer,load_config
from stage2_io import preprocess,json_text
from mask_display import MaskDisplay,percentile
p=argparse.ArgumentParser();p.add_argument('--mode',choices=['off','mock','missing','device'],required=True)
p.add_argument('--rounds',type=int,default=12);a=p.parse_args()
cv2.setNumThreads(1)
samples=Path('/home/huzhen/linux_stage2_20261030/input/samples/run-d5d7ca2a5b784049be1bf39a964ebed5')
paths=sorted(samples.glob('real-*.png'))
assert len(paths)==3
frames=[cv2.imread(str(f)) for f in paths]
assert all(f.shape==(480,640,3) and f.dtype==np.uint8 for f in frames)
manifest=[{'file':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in paths]
cfg=load_config(str(B/'delivery/app/config/algorithm.json'))
cfg.gesture_confirm_frames=1;cfg.gesture_hold_frames=0;cfg.calibration_stable_frames=1;cfg.validate()
recognizer=HeadlessRecognizer(cfg,automatic=True,edge_assist=True,lowtip_tracking=True)
class MockBackend:
    def __init__(self):self.writes=0;self.closed=False;self.last_hash=None
    def write(self,data):
        assert isinstance(data,bytes) and len(data)==76800
        time.sleep(.02) # synthetic IO delay; not measured MMIO performance
        self.last_hash=hashlib.sha256(data).hexdigest();self.writes+=1
    def status(self):return (0x4d534b31,1,0x00f00140,76800,0,0,0,0)
    def close(self):self.closed=True
mock=MockBackend()
kwargs={}
if a.mode=='mock':kwargs['_backend_factory']=lambda:mock
if a.mode=='missing':kwargs['device']='/nonexistent-gesture-test-device'
display=MaskDisplay(enabled=a.mode!='off',**kwargs)
time.sleep(.1)
for f in frames:recognizer.process(preprocess(f))
rows=[];contract=[];cpu0=time.process_time();t0=time.monotonic()
try:
    for n in range(a.rounds):
        for f in frames:
            t=time.monotonic();small=preprocess(f);t1=time.monotonic()
            result,masks,timing=recognizer.process(small);t2=time.monotonic()
            display.submit(masks['final_hand_mask']);t3=time.monotonic()
            m=masks['final_hand_mask']
            # Diagnostics after measured loop interval, same off/on overhead.
            contract.append({'shape':list(m.shape),'dtype':str(m.dtype),'unique':np.unique(m).tolist()})
            rows.append({'process_ms':(t2-t1)*1000,'submit_ms':(t3-t2)*1000,'loop_ms':(t3-t)*1000,
                         'result':result,'mask_sha256':hashlib.sha256(m.tobytes()).hexdigest()})
finally:
    elapsed=time.monotonic()-t0;cpu1=time.process_time();stats=display.close()
def summ(key):
    v=[x[key] for x in rows];return {'p50':percentile(v,.5),'p95':percentile(v,.95),'max':max(v)}
# Semantic outputs and raw masks must remain identical; timings intentionally excluded.
semantic=[{'result':x['result'],'mask_sha256':x['mask_sha256']} for x in rows]
cpu=cpu1-cpu0
status_text=Path('/proc/self/status').read_text()
rss=next((int(line.split()[1]) for line in status_text.splitlines() if line.startswith('VmHWM:')),None)
report={'mode':a.mode,'input_manifest':manifest,'frames':len(rows),'rounds':a.rounds,'rows':rows,
 'mask_contract':contract,'semantic_sha256':hashlib.sha256(json_text(semantic).encode()).hexdigest(),
 'recognizer_fps':len(rows)/sum(x['process_ms']/1000 for x in rows),'loop_fps':len(rows)/elapsed,
 'elapsed_seconds':elapsed,'process_ms':summ('process_ms'),'submit_ms':summ('submit_ms'),'loop_ms':summ('loop_ms'),
 'cpu_seconds':cpu,'cpu_percent':100*cpu/elapsed,'peak_rss_kib':rss,'rss_scope':'/proc/self/status VmHWM for QEMU host process, not standalone ARM-board RSS','display':stats,
 'python':sys.version,'numpy':np.__version__,'opencv':cv2.__version__,'machine':platform.machine(),
 'camera_dma_errors':None,'physical_scanout_verified':False,'actual_arm_board':False,
 'scope':'QEMU ARM user-mode; historical fixed real input; mock mode has synthetic 20ms backend, NOT real HDMI-on comparison'}
(B/'evidence/replay_{}.json'.format(a.mode)).write_text(json_text(report))
print(json.dumps({k:v for k,v in report.items() if k not in ('rows','mask_contract')},indent=2))
assert all(x['shape']==[240,320] and x['dtype']=='uint8' and set(x['unique']).issubset({0,255}) for x in contract)
if a.mode in ('mock','device'):assert stats['written']>0 and not stats['error']
if a.mode=='missing':assert stats['error'] and stats['written']==0
