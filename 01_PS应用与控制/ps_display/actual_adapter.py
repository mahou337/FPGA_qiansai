"""Actual current recognizer only; explicit existing camera preprocessing, no UART."""
import sys
from pathlib import Path
B=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(B/'delivery/app/ps'))
from headless import HeadlessRecognizer,load_config
from stage2_io import preprocess
import cv2
class Adapter(object):
    def __init__(self):
        cfg=load_config(str(B/'delivery/app/config/algorithm.json'))
        cfg.gesture_confirm_frames=1;cfg.gesture_hold_frames=0;cfg.calibration_stable_frames=1
        cfg.validate();cv2.setNumThreads(1)
        self.recognizer=HeadlessRecognizer(cfg,automatic=True,edge_assist=True,lowtip_tracking=True)
    def process(self,frame):return self.recognizer.process(preprocess(frame,0))
def make_recognizer():return Adapter()
