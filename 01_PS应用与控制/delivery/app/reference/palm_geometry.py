"""Palm candidate geometry. No axis estimation, rotation, or tracking."""
from compat_records import MISSING
from compat_cv import find_contours
from compat_records import dataclass
import cv2
import numpy as np

def find_palm_center(mask):
    """Reused distance-transform maximum with explicit zero image border."""
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[1:-1, 1:-1]
    radius = float(distance.max())
    if radius <= 0:
        return (None, 0.0, distance)
    yy, xx = np.nonzero(mask)
    py, px = np.nonzero(distance >= radius - 1e-05)
    best = np.argmin((px - xx.mean()) ** 2 + (py - yy.mean()) ** 2)
    return ((int(px[best]), int(py[best])), radius, distance)

def isolate_candidate(mask, candidate):
    selected = np.zeros_like(mask)
    if candidate is not None:
        x, y = map(int, candidate['contour'][0, 0])
        _, labels = cv2.connectedComponents(mask, connectivity=8)
        label = int(labels[y, x])
        if label:
            selected[labels == label] = 255
    return selected

@dataclass
class PalmGeometry:
    _field_specs = [('mask', MISSING), ('contour', MISSING), ('distance', MISSING), ('center', MISSING), ('radius', MISSING), ('valid', MISSING), ('info', MISSING)]

def analyze_palm(clean_mask, candidate, min_radius=3):
    selected = isolate_candidate(clean_mask, candidate)
    center, radius, distance = find_palm_center(selected)
    contour = np.empty((0, 1, 2), np.int32) if candidate is None else candidate['contour']
    area = 0.0 if candidate is None else float(cv2.contourArea(contour))
    perimeter = 0.0 if candidate is None else float(cv2.arcLength(contour, True))
    clipped = any((np.any(edge) for edge in (selected[0], selected[-1], selected[:, 0], selected[:, -1])))
    fraction = float(np.count_nonzero(selected) / selected.size)
    filled = np.zeros_like(selected)
    if candidate is not None:
        cv2.drawContours(filled, [contour], -1, 255, -1)
    holes = float(np.count_nonzero((filled > 0) & (selected == 0)) / max(np.count_nonzero(filled), 1))
    reasons = []
    if center is None:
        reasons.append('no_region')
    elif radius < min_radius:
        reasons.append('palm_too_small')
    if fraction > 0.8:
        reasons.append('region_covers_most_of_image')
    if holes > 0.1:
        reasons.append('fragmented_or_holey_mask')
    valid = not reasons
    info = {'center_xy': None if center is None else list(center), 'radius_px': radius, 'area_px2': area, 'perimeter_px': perimeter, 'valid': valid, 'touches_border': bool(clipped), 'foreground_fraction': fraction, 'hole_fraction': holes, 'reasons': reasons, 'is_confirmed_hand': False}
    return PalmGeometry(selected, contour, distance, center, radius, valid, info)

def distance_view(palm):
    if palm.center is None:
        return np.zeros((*palm.mask.shape, 3), np.uint8)
    heat = cv2.applyColorMap(np.clip(palm.distance * 255 / palm.radius, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
    heat[palm.mask == 0] = 0
    cv2.circle(heat, palm.center, max(1, int(round(palm.radius))), (255, 255, 255), 1)
    cv2.drawMarker(heat, palm.center, (255, 255, 255), cv2.MARKER_CROSS, 10, 1)
    return heat
