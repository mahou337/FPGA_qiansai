"""Static empty-scene reference; only explicit B capture can update it."""
from compat_records import MISSING
from compat_cv import find_contours
import cv2
import numpy as np

def roi_mask(shape, roi=None):
    mask = np.zeros(shape[:2], np.uint8)
    if roi is None:
        mask[:] = 255
    else:
        x, y, width, height = roi
        mask[y:min(y + height, shape[0]), x:min(x + width, shape[1])] = 255
    return mask

class BackgroundSubtractor:

    def __init__(self, enabled=False, capture_frames=20, threshold=25, roi=None):
        self.enabled = enabled
        self.capture_frames = capture_frames
        self.threshold = threshold
        self.roi = roi
        self.reference = None
        self.samples = None
        self.last_info = {}

    def start_capture(self):
        self.enabled = True
        self.reference = None
        self.samples = []

    def clear(self):
        self.reference = None
        self.samples = None

    def toggle(self):
        self.enabled = not self.enabled
        self.samples = None
        return self.enabled

    def apply(self, frame, skin):
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError('Background input must be raw uint8 BGR')
        if skin.shape != frame.shape[:2] or skin.dtype != np.uint8:
            raise ValueError('Skin mask must be uint8 and match the frame resolution')
        invalidated = self.reference is not None and self.reference.shape != frame.shape or (bool(self.samples) and self.samples[0].shape != frame.shape)
        if invalidated:
            self.clear()
        if self.samples is not None:
            self.samples.append(frame.copy())
            if len(self.samples) >= self.capture_frames:
                self.reference = np.median(np.stack(self.samples), axis=0).astype(np.uint8)
                self.samples = None
        ready = self.reference is not None
        active = self.enabled and ready
        if ready:
            # Native OpenCV channel maxima avoid the per-pixel NumPy axis
            # reduction on the ARM CPU, with identical uint8 threshold semantics.
            channels = cv2.split(cv2.absdiff(frame, self.reference))
            difference = cv2.max(cv2.max(channels[0], channels[1]), channels[2])
            _, foreground = cv2.threshold(difference, self.threshold, 255, cv2.THRESH_BINARY)
        else:
            foreground = np.full(skin.shape, 255, np.uint8)
        combined = cv2.bitwise_and(skin, foreground) if active else skin.copy()
        combined = cv2.bitwise_and(combined, roi_mask(skin.shape, self.roi))
        if not ready:
            status = 'Background not calibrated'
            if self.samples is not None:
                status += ' | capture {0}/{1}'.format(len(self.samples), self.capture_frames)
        else:
            status = 'BG {0} | calibrated | T={1}'.format('ON' if self.enabled else 'OFF', self.threshold)
        self.last_info = {'enabled': self.enabled, 'ready': ready, 'calibrated': ready, 'effective': active, 'skin_only_fallback': self.enabled and (not ready), 'capturing': self.samples is not None, 'status': status, 'resolution_invalidated': invalidated, 'difference_threshold': self.threshold, 'roi_xywh': None if self.roi is None else list(self.roi), 'foreground_is_bypass': not ready, 'capture_frames': self.capture_frames, 'reference_resolution': None if not ready else [self.reference.shape[1], self.reference.shape[0]], 'method': 'fixed median raw BGR reference; max(absdiff) > threshold; no automatic updates'}
        return (combined, foreground)

    def annotate(self, image):
        if self.roi is not None:
            x, y, width, height = self.roi
            cv2.rectangle(image, (x, y), (x + width - 1, y + height - 1), (255, 255, 0), 1)
        lines = [self.last_info.get('status', ''), 'BG requested: {0} | B capture / G toggle / C clear'.format('ON' if self.enabled else 'OFF')]
        for index, text in enumerate(lines):
            point = (5, image.shape[0] - 24 + index * 15)
            cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 255, 255), 1, cv2.LINE_AA)
BackgroundFilter = BackgroundSubtractor

def make_filter(config):
    return BackgroundSubtractor(config.background_enabled, config.background_frames, config.background_threshold, config.detection_roi)
