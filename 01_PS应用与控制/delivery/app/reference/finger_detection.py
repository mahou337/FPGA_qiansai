"""Contour, hull, defect and radial-curvature fingertip candidates."""
from compat_records import MISSING
from compat_cv import find_contours
from compat_records import dataclass
import cv2
import numpy as np

@dataclass
class FingerFeatures:
    _field_specs = [('hull', MISSING), ('tips', MISSING), ('defects', MISSING), ('info', MISSING)]

    def to_dict(self):
        return {**self.info, 'tips': self.tips, 'defects': self.defects, 'hull_xy': self.hull.reshape(-1, 2).tolist()}

def angle_degrees(a, b):
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 180.0 if norm < 1e-08 else float(np.degrees(np.arccos(np.clip(np.dot(a, b) / norm, -1, 1))))

def sample_contour(contour, step):
    points = contour.reshape(-1, 2).astype(float)
    points = np.vstack((points, points[:1]))
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    distance = np.r_[0, np.cumsum(lengths)]
    if distance[-1] <= 0:
        return points[:1]
    count = min(2048, max(16, int(np.ceil(distance[-1] / step))))
    positions = np.linspace(0, distance[-1], count, endpoint=False)
    return np.column_stack([np.interp(positions, distance, points[:, axis]) for axis in (0, 1)])

def _tip_width(mask, point, center, radius):
    vector = point - center
    vector /= max(float(np.linalg.norm(vector)), 1e-08)
    side = np.array([-vector[1], vector[0]])
    q = np.arange(-int(np.ceil(radius)), int(np.ceil(radius)) + 1)
    xy = point - 0.45 * radius * vector + q[:, None] * side
    values = cv2.remap(mask, xy[:, 0].astype(np.float32)[None], xy[:, 1].astype(np.float32)[None], cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)[0] > 0
    middle = len(q) // 2
    if not values[middle]:
        occupied = np.flatnonzero(values)
        if not len(occupied):
            return 0.0
        middle = int(occupied[np.argmin(abs(occupied - middle))])
        if abs(q[middle]) > 0.35 * radius:
            return 0.0
    left = right = middle
    while left > 0 and values[left - 1]:
        left -= 1
    while right + 1 < len(values) and values[right + 1]:
        right += 1
    return float(right - left + 1) / radius

def separated_tip_peaks(tip, old, palm):
    """Close supported peaks are distinct only across a visible mask gap.

    The old fixed 0.65*palm-radius suppression can merge neighboring real
    fingertips. Do not relax it for duplicate peaks on the same finger.
    """
    a, b = np.asarray(tip['xy'], float), np.asarray(old['xy'], float)
    distance = float(np.linalg.norm(a - b))
    if distance >= 0.65 * palm.radius:
        return True
    if distance < 0.35 * palm.radius or not (tip['valley_support'] and old['valley_support']):
        return False
    # Sample the chord between rounded fingertip centers. A true gap contains
    # background; a second local maximum of the same finger does not.
    xy = np.rint(a[None, :] + np.linspace(0.1, 0.9, 21)[:, None] * (b - a)[None, :]).astype(int)
    outside = palm.mask[xy[:, 1], xy[:, 0]] == 0
    return bool(np.count_nonzero(outside) >= 5)

def detect_fingers(palm, min_tip_ratio=1.45, min_defect_ratio=0.3, separate_close_tips=False):
    contour, radius = (palm.contour, palm.radius)
    empty = np.empty((0, 1, 2), np.int32)
    if not palm.valid or len(contour) < 4:
        return FingerFeatures(empty, [], [], {'valid': False, 'reason': 'invalid_palm', 'tip_count': 0})
    hull = cv2.convexHull(contour)
    indices = cv2.convexHull(contour, returnPoints=False)
    defects = []
    defect_error = None
    try:
        raw = cv2.convexityDefects(contour, indices) if indices is not None and len(indices) >= 3 else None
    except cv2.error:
        raw, defect_error = (None, 'non_simple_contour')
    center = np.asarray(palm.center, dtype=float)
    if raw is not None:
        for start, end, far, depth_fixed in raw[:, 0]:
            a, b, v = contour[[start, end, far], 0].astype(float)
            depth = float(depth_fixed) / 256.0
            angle = angle_degrees(a - v, b - v)
            accepted = depth >= min_defect_ratio * radius and angle <= 110 and (0.4 <= np.linalg.norm(v - center) / radius <= 1.8) and (min(np.linalg.norm(a - center), np.linalg.norm(b - center)) >= 1.3 * radius)
            defects.append({'start_xy': a.astype(int).tolist(), 'end_xy': b.astype(int).tolist(), 'valley_xy': v.astype(int).tolist(), 'depth_fixed': int(depth_fixed), 'depth_px': depth, 'depth_ratio': depth / radius, 'angle_degrees': angle, 'accepted': bool(accepted)})
    points = sample_contour(contour, max(0.8, 0.04 * radius))
    points = sum((np.roll(points, offset, axis=0) for offset in (-2, -1, 0, 1, 2))) / 5
    radii = np.linalg.norm(points - center, axis=1)
    spacing = float(cv2.arcLength(contour, True)) / len(points)
    offset = max(2, int(round(0.4 * radius / max(spacing, 0.1))))
    offset = min(offset, max(2, len(points) // 8))
    window = max(2, offset // 2)
    # Same circular radial-max test, evaluated in NumPy rather than one Python
    # iteration and temporary array for every contour point on ARM.
    maxima = radii.copy()
    for shift in range(1, window + 1):
        np.maximum(maxima, np.roll(radii, shift), out=maxima)
        np.maximum(maxima, np.roll(radii, -shift), out=maxima)
    peak_ids = np.flatnonzero((radii / radius >= min_tip_ratio) & (radii >= maxima - 1e-05))
    candidates = []
    for index in peak_ids:
        point = points[index]
        ratio = radii[index] / radius
        curvature = angle_degrees(points[(index - offset) % len(points)] - point, points[(index + offset) % len(points)] - point)
        support = any((d['accepted'] and min(np.linalg.norm(point - d['start_xy']), np.linalg.norm(point - d['end_xy'])) <= 0.6 * radius for d in defects))
        if curvature > (120 if support else 110):
            continue
        width = _tip_width(palm.mask, point, center, radius)
        if not 0.12 <= width <= 0.85:
            continue
        x, y = np.rint(point).astype(int)
        h, w = palm.mask.shape
        if min(x, y, w - 1 - x, h - 1 - y) < max(2, 0.12 * radius):
            continue
        if not support and (not (curvature <= 110 and ratio >= 1.6 and (width <= 0.7))):
            continue
        candidates.append({'xy': [int(x), int(y)], 'radius_ratio': float(ratio), 'angle_rad': float(np.arctan2(point[1] - center[1], point[0] - center[0])), 'curvature_degrees': curvature, 'width_ratio': width, 'valley_support': bool(support), 'score': float((180 - curvature) / 180 + 0.25 * support)})
    tips = []
    for tip in sorted(candidates, key=lambda candidate: candidate['score'], reverse=True):
        if all((separated_tip_peaks(tip, old, palm) if separate_close_tips else
                np.linalg.norm(np.asarray(tip['xy']) - old['xy']) >= 0.65 * radius) for old in tips):
            tips.append(tip)
    tips.sort(key=lambda tip: tip['angle_rad'])
    valid = defect_error is None and len(tips) <= 5
    return FingerFeatures(hull, tips, defects, {'valid': valid, 'reason': defect_error or ('too_many_tips' if len(tips) > 5 else 'ok'), 'tip_count': len(tips), 'valley_count': sum((d['accepted'] for d in defects))})

def draw_finger_detection(bgr, palm, features, gesture, config):
    """Only measured tips get markers; inferred folded states stay in text."""
    height, width = bgr.shape[:2]
    view = np.zeros((height + 170, max(width, 520), 3), np.uint8)
    view[:height, :width] = bgr
    if len(palm.contour) and config.show_contour:
        cv2.drawContours(view, [palm.contour], -1, (0, 190, 0), 1)
    if palm.center is not None:
        cv2.circle(view, palm.center, max(1, int(round(palm.radius))), (255, 255, 255), 1)
        cv2.drawMarker(view, palm.center, (255, 255, 255), cv2.MARKER_CROSS, 10, 1)
    if len(features.hull) and config.show_hull:
        cv2.polylines(view, [features.hull], True, (255, 180, 0), 1)
    if config.show_defects:
        for defect in features.defects:
            if defect['accepted']:
                cv2.circle(view, tuple(defect['valley_xy']), 3, (0, 255, 255), -1)
    identities = gesture['raw']['tip_identities']
    motion = gesture['raw'].get('palm_motion', {})
    if motion.get('used_for_identity'):
        anchor = tuple(np.rint(motion['center_xy']).astype(int))
        cv2.drawMarker(view, anchor, (255, 140, 255), cv2.MARKER_CROSS, 9, 1)
    rejected = {item['tip_index']: item for item in gesture['raw'].get('rejected_tip_candidates', [])}
    if config.show_tips:
        for index, tip in enumerate(features.tips):
            name = identities.get(str(index))
            confirmed = name is not None and gesture['reliable']
            color = (0, 255, 0) if confirmed else (0, 255, 255)
            point = tuple(tip['xy'])
            cv2.circle(view, point, 5, color, 2)
            label = 'short bump' if index in rejected else name if confirmed else name + '?' if name else 'tip?'
            cv2.putText(view, label, (point[0] + 4, max(12, point[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
    color = (0, 255, 0) if gesture['reliable'] else (0, 255, 255)
    cv2.putText(view, 'Gesture={0}  {1}'.format(gesture['code'], gesture['status']), (8, height + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1, cv2.LINE_AA)
    cv2.putText(view, 'Raw={0}  candidates={1}  extended={2}'.format(gesture['raw']['code'], len(features.tips), gesture['raw'].get('matched_tip_count', 0)), (8, height + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 230, 230), 1)
    colors = {'1': (0, 255, 0), '0': (0, 0, 255), '?': (0, 255, 255)}
    for index, (name, state) in enumerate([(name, gesture['raw']['states'][name]) for name in ('Thumb', 'Index', 'Middle', 'Ring')]):
        x, y = (8 + index % 2 * 235, height + 64 + index // 2 * 23)
        cv2.putText(view, '{0}: {1}'.format(name, state), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[state], 1)
    cv2.putText(view, gesture['raw']['reason'][:75], (8, height + 110), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 220, 255), 1)
    raw = gesture['raw']
    if raw['reason'] == 'show_full_open_hand_to_establish_identity_reference':
        reset_reason = raw.get('reference_geometry', {}).get('last_reset_reason', 'unknown')
        tracking = 'Open ALL FIVE | reset: ' + reset_reason[:42]
    elif 'hand_changed' in raw['reason']:
        tracking = 'Hand changed: press K, then open ALL FIVE'
    elif 'lost' in raw['reason']:
        tracking = 'Show 3+ clear fingers to revalidate tracking'
    else:
        tracking = 'Matched={0} | unchecked={1}f | LK={2}'.format(raw.get('matched_tip_count', 0), raw.get('reference_age'), 'OK' if motion.get('used_for_identity') else 'OFF')
    cv2.putText(view, tracking, (8, height + 131), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (220, 220, 220), 1)
    cv2.putText(view, '2026-10-29 motion3 | PARTIAL / UNKNOWN -> no command', (8, height + 156), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (180, 180, 180), 1)
    return view
