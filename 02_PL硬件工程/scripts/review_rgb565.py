"""Measure format quantization sensitivity; never a recognition accuracy score."""
from pathlib import Path
import json
import sys
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ps'))
from headless import HeadlessRecognizer
from skin_detection import Config,skin_mask
paths=sorted((ROOT.parent/'gesture_classic/results').glob('*/original.png'))
if not paths: raise SystemExit('No original snapshot fixtures')
rows=[]
for path in paths:
    im=cv2.imread(str(path)); h,w=im.shape[:2]; cfg=Config(width=w,height=h)
    quantized=cv2.cvtColor(cv2.cvtColor(im,cv2.COLOR_BGR2BGR565),cv2.COLOR_BGR5652BGR)
    changed=int(np.count_nonzero(skin_mask(im,cfg)!=skin_mask(quantized,cfg)))
    result,_,timing=HeadlessRecognizer(cfg).process(quantized)
    rows.append(dict(image=str(path),width=w,height=h,skin_mask_changed_pixels=changed,
        skin_mask_changed_fraction=changed/(w*h),rgb565_status_single_image=result['status'],
        host_processing_ms=timing['total_ms']))
report=dict(note='Independent existing snapshots; NOT actual camera output or recognition accuracy. PC timing is not ARM timing.',
    sample_count=len(rows),mean_skin_mask_changed_fraction=float(np.mean([r['skin_mask_changed_fraction'] for r in rows])),
    max_skin_mask_changed_fraction=max(r['skin_mask_changed_fraction'] for r in rows),samples=rows)
(ROOT/'build/rgb565_review.json').write_text(json.dumps(report,indent=2)+'\n')
print({k:v for k,v in report.items() if k!='samples'})
