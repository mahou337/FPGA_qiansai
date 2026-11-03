"""No empty-scene learning: constrained dark-background silhouette mode.

Not general-purpose object recognition. Only use a dark matte backdrop with one
unobstructed hand. Bright clutter is rejected where possible, not recognized.
"""
import cv2
import numpy as np
from background_subtraction import roi_mask
from gesture_classifier import open_hand_order, wrapped

class BlackBackground:
    def __init__(self, roi=None):
        self.roi = roi
        self.threshold = 25  # interface compatibility; not the silhouette threshold
        self.samples = None
        self.reference = None
        self.enabled = True
        self.last_info = {}

    def apply(self, frame, skin):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = roi_mask(gray.shape, self.roi)
        values = gray[roi > 0]
        level, unused = cv2.threshold(values.reshape(-1, 1), 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        level = max(60.0, min(160.0, float(level)))
        foreground = cv2.bitwise_and(cv2.inRange(gray, int(level) + 1, 255), roi)
        dark_fraction = float(np.count_nonzero(values <= 60)) / max(1, values.size)
        # A predominantly bright scene is outside this operating mode. Never
        # silently learn a hand into a new background or bypass this check.
        effective = dark_fraction >= 0.30
        if not effective:
            foreground[:] = 0
        # White tabletop corners are not hands. A clipped hand touching two
        # borders is also rejected rather than inferred from incomplete shape.
        count, labels, stats, centers = cv2.connectedComponentsWithStats(foreground, 8)
        height, width = foreground.shape
        removed = 0
        for label in range(1, count):
            x, y, w, h, area = [int(v) for v in stats[label]]
            edges = int(x == 0) + int(y == 0) + int(x + w == width) + int(y + h == height)
            if edges >= 2:
                foreground[labels == label] = 0
                removed += 1
        self.last_info = {'enabled': True, 'ready': effective, 'effective': effective,
            'calibrated': False, 'capturing': False, 'skin_only_fallback': False,
            'method': 'automatic_dark_backdrop_luminance_otsu_bounded_60_160',
            'luminance_threshold': level, 'dark_fraction': dark_fraction,
            'minimum_dark_fraction': 0.30, 'removed_corner_components': removed,
            'foreground_is_bypass': False, 'status': 'AUTO_DARK_READY' if effective else 'NEED_DARK_BACKDROP'}
        return foreground.copy(), foreground

class OpenHandObserver:
    """Observe native geometry independently of an old tracking reference."""
    def __init__(self, required=1):
        self.required = max(1, required)
        self.previous = None
        self.count = 0

    def update(self, palm, features):
        order = open_hand_order(features.tips) if palm.valid and features.info.get('valid') else None
        if order is None or features.info.get('valley_count', 0) < 3:
            self.previous = None
            self.count = 0
            return False
        angles = np.asarray([features.tips[i]['angle_rad'] for i in order])
        ratios = np.asarray([features.tips[i]['radius_ratio'] for i in order])
        current = (angles, ratios, np.asarray(palm.center, float), palm.radius)
        old = self.previous
        stable = old is not None and np.max(np.abs(wrapped(angles - old[0]))) < np.deg2rad(12)
        stable = stable and np.max(np.abs(ratios / old[1] - 1)) < 0.18
        stable = stable and np.linalg.norm(current[2] - old[2]) < 0.35 * palm.radius
        stable = stable and 0.85 < palm.radius / old[3] < 1.18
        self.count = min(self.required, self.count + 1) if stable else 1
        self.previous = current
        return self.count >= self.required
