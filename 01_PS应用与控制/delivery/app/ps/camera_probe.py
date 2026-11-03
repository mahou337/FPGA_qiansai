"""Capture raw-board fixtures before evaluating recognition. Linux only."""
import argparse
import json
from pathlib import Path
import time
import cv2
from hardware_vga import HardwareVGA

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',required=True)
    p.add_argument('--frames',type=int,default=10)
    p.add_argument('--color-bars',action='store_true',help='OV5640 PRE ISP 0x503D bit7')
    p.add_argument('--device',default='/dev/gesture-camera')
    p.add_argument('--table',default=str(Path(__file__).resolve().parents[1]/'config/ov5640_vga_rgb565.json'))
    args=p.parse_args()
    if args.frames<1: p.error('frames must be positive')
    output=Path(args.directory)
    output.mkdir(parents=True,exist_ok=False)
    hw=HardwareVGA(args.device)
    rows=[]
    try:
        hw.initialize(args.table)
        if args.color_bars: hw.camera_write(0x503d,0x80); time.sleep(.15)
        for i in range(args.frames):
            start=time.monotonic(); seq,image=hw.capture()
            name='{0:05d}.png'.format(i)
            if not cv2.imwrite(str(output/name),image): raise OSError('Image save failed')
            rows.append(dict(frame_id=seq,image=name,capture_ms=(time.monotonic()-start)*1000))
        (output/'capture.json').write_text(json.dumps({'color_bars':args.color_bars,'frames':rows},indent=2))
    finally:
        try:
            if args.color_bars and not (hw.read(12)&2): hw.camera_write(0x503d,0)
        finally: hw.close()

if __name__=='__main__': main()
