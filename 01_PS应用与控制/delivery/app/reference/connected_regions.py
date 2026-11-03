"""8-connected candidate selection. A selected skin region is not a confirmed hand."""
from compat_records import MISSING
from compat_cv import find_contours
import cv2
import numpy as np
from background_subtraction import roi_mask

def select_hand_region(clean, min_area=500, max_fraction=0.8, ambiguity_ratio=0.65, roi=None):
    region = roi_mask(clean.shape, roi)
    scoped = cv2.bitwise_and(clean, region)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(scoped, connectivity=8)
    height, width = scoped.shape
    if roi is None:
        rx, ry, rw, rh = (0, 0, width, height)
    else:
        rx, ry, rw, rh = roi
        rw, rh = (max(0, min(rx + rw, width) - rx), max(0, min(ry + rh, height) - ry))
    roi_area = int(np.count_nonzero(region))
    entries, eligible = ([], [])
    for label in range(1, count):
        x, y, w, h, area = map(int, stats[label])
        reasons = []
        if area < min_area:
            reasons.append('below_min_area')
        if area > max_fraction * roi_area:
            reasons.append('exceeds_max_roi_fraction')
        entry = {'label': label, 'pixel_area': area, 'bbox_xywh': [x, y, w, h], 'centroid_xy': [float(v) for v in centers[label]], 'touches_image_border': x == 0 or y == 0 or x + w == width or (y + h == height), 'touches_roi_border': x == rx or y == ry or x + w == rx + rw or (y + h == ry + rh), 'eligible': not reasons, 'rejection_reasons': reasons}
        entries.append(entry)
        if not reasons:
            eligible.append(entry)
    eligible.sort(key=lambda e: e['pixel_area'], reverse=True)
    ambiguous = len(eligible) > 1 and eligible[1]['pixel_area'] >= ambiguity_ratio * eligible[0]['pixel_area']
    selected = None if ambiguous or not eligible else eligible[0]
    final = np.zeros_like(clean)
    candidate = None
    if selected is not None:
        final[labels == selected['label']] = 255
        contours, _ = find_contours(final, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        candidate = {'contour': contour, 'area': float(cv2.contourArea(contour)), 'bbox': tuple(selected['bbox_xywh']), 'component_pixel_area': selected['pixel_area'], 'component_label': selected['label'], 'centroid_xy': selected['centroid_xy']}
    info = {'connectivity': 8, 'component_count': count - 1, 'eligible_count': len(eligible), 'components': entries, 'ambiguous': ambiguous, 'status': 'Ambiguous Skin Regions' if ambiguous else 'Candidate Skin Region' if selected else 'No Hand Region', 'selected_label': None if selected is None else selected['label'], 'selected_pixel_area': 0 if selected is None else selected['pixel_area'], 'min_pixel_area': min_area, 'max_roi_fraction': max_fraction, 'ambiguity_area_ratio': ambiguity_ratio, 'roi_area_pixels': roi_area, 'selection_rule': 'largest eligible only when second/largest area < ambiguity ratio; no identity claim', 'is_confirmed_hand': False}
    return (final, candidate, info)
