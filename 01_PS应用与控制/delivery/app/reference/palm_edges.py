"""Conservative interior-edge assistance, never an independent hand classifier.

A stable open-hand edge baseline suppresses pre-existing palm creases. Only an
already uniquely assigned, partly retracted unknown finger can become folded;
new curved interior edges must persist and ordinary final debounce still runs.
"""
import cv2
import numpy as np
from compat_cv import find_contours

NAMES = ('Thumb', 'Index', 'Middle', 'Ring')
SIZE, RADIUS, CENTER = 128, 26.0, 64.0

class PalmEdgeAssist:
    def __init__(self):
        self.reset()

    def reset(self):
        self.baseline = None
        self.baseline_count = 0
        self.signature = None
        self.counts = dict((n, 0) for n in NAMES)
        self.positions = {}
        self.last_images = {}
        self.last_info = {}

    def _clear_votes(self):
        self.counts = dict((n, 0) for n in NAMES)
        self.positions = {}

    def _normalize(self, frame, palm, raw, reference):
        angle = float(reference['angles'][2]) if reference is not None else -np.pi / 2
        radius = float(raw.get('reference_geometry', {}).get('effective_normalization_radius_px') or palm.radius)
        u = np.array([np.cos(angle), np.sin(angle)])
        v = np.array([-u[1], u[0]])
        scale = RADIUS / max(1.0, radius)
        linear = np.vstack((v, -u)) * scale
        center = np.asarray(palm.center, float)
        matrix = np.column_stack((linear, np.array([CENTER, CENTER]) - linear.dot(center)))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        patch = cv2.warpAffine(gray, matrix, (SIZE, SIZE), flags=cv2.INTER_LINEAR)
        mask = cv2.warpAffine(palm.mask, matrix, (SIZE, SIZE), flags=cv2.INTER_NEAREST)
        # Suppress silhouette edges, image padding, and two pixels just inside
        # the hand boundary. Only interior structure is eligible evidence.
        interior = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2,
                             borderType=cv2.BORDER_CONSTANT, borderValue=0)
        blurred = cv2.GaussianBlur(patch, (3, 3), 0)
        edges = cv2.bitwise_and(cv2.Canny(blurred, 35, 90, L2gradient=True), interior)
        return patch, edges, angle

    def _cap(self, fresh, angle):
        yy, xx = np.indices(fresh.shape)
        x, y = xx - CENTER, yy - CENTER
        # angle is relative to the middle finger, which points upward here.
        direction = np.array([np.sin(angle), -np.cos(angle)])
        side = np.array([-direction[1], direction[0]])
        along = x * direction[0] + y * direction[1]
        across = x * side[0] + y * side[1]
        roi = ((along >= 0.65 * RADIUS) & (along <= 1.65 * RADIUS) &
               (np.abs(across) <= 0.38 * RADIUS))
        local = cv2.bitwise_and(fresh, roi.astype(np.uint8) * 255)
        contours, unused = find_contours(local, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        best = None
        for contour in contours:
            points = contour.reshape(-1, 2).astype(float)
            if len(points) < 12:
                continue
            unique = np.unique(points, axis=0)
            if len(unique) < 9:
                continue
            relative = unique - CENTER
            a, s = relative.dot(direction), relative.dot(side)
            width, depth = float(np.ptp(s)), float(np.ptp(a))
            if not (0.22 * RADIUS <= width <= 0.76 * RADIUS and
                    0.12 * RADIUS <= depth <= 0.75 * RADIUS):
                continue
            values = np.linalg.eigvalsh(np.cov(unique.T))
            curvature = float(values[0] / max(values[1], 1e-6))
            if curvature < 0.04:
                continue  # straight palm line, not curved cap evidence
            candidate = {'center': np.mean(unique, axis=0).tolist(),
                         'pixels': len(unique), 'width_px': width,
                         'depth_px': depth, 'curvature_ratio': curvature}
            if best is None or candidate['pixels'] > best['pixels']:
                best = candidate
        return best

    def fuse(self, raw, observations, ready, gate_reason):
        """Fusion is independently testable; no classifier reference is mutated."""
        result = dict(raw)
        evidence = {'baseline_ready': bool(ready), 'baseline_frames': self.baseline_count,
                    'gate': gate_reason, 'geometry_code': raw['code'],
                    'geometry_reason': raw['reason'], 'fingers': {}, 'changed': []}
        result['edge_assistance'] = evidence
        motion = raw.get('palm_motion', {})
        roots = raw.get('finger_root_graph_match') or {}
        pose_verified = bool((motion.get('valid') and motion.get('used_for_identity')) or
                             (len(roots.get('slots', [])) >= 3 and
                              roots.get('relative_length_residual', 1) <= 0.08 and
                              roots.get('source') == 'observed_tip_to_valley_lengths_angles_and_order'))
        evidence['identity_pose_verified'] = pose_verified
        allowed = (ready and pose_verified and gate_reason == 'eligible' and
                   raw.get('reason') == 'unobserved_or_merged_finger' and
                   raw.get('matched_tip_count', 0) >= 2 and
                   raw.get('reference_age') is not None and 0 <= raw['reference_age'] <= 2)
        states = dict(raw['states'])
        finger_evidence = dict((k, dict(v)) for k, v in raw.get('finger_evidence', {}).items())
        for name in NAMES:
            e = finger_evidence.get(name, {})
            fraction = e.get('extension_fraction', -1)
            eligible = (allowed and states.get(name) == '?' and
                        e.get('reason') == 'tip_absent_but_sector_not_retracted' and
                        e.get('measured_tip_index') is None and
                        not e.get('image_or_roi_edge_intersects_sector', True) and
                        0.70 < fraction <= 0.85)
            observation = observations.get(name) if eligible else None
            if observation is not None:
                previous = self.positions.get(name)
                position = np.asarray(observation['center'], float)
                stable = previous is not None and np.linalg.norm(position - previous) <= 0.25 * RADIUS
                self.counts[name] = min(3, self.counts[name] + 1) if stable else 1
                self.positions[name] = position
            else:
                self.counts[name] = 0
                self.positions.pop(name, None)
            evidence['fingers'][name] = {'eligible': bool(eligible),
                'new_curved_edge': observation, 'consecutive_frames': self.counts[name]}
            if self.counts[name] >= 3:
                states[name] = '0'
                finger_evidence[name]['state'] = '0'
                finger_evidence[name]['reason'] = 'retraction_plus_new_interior_cap_edge'
                evidence['changed'].append(name)
        if evidence['changed']:
            result['states'] = states
            result['finger_evidence'] = finger_evidence
            result['code'] = ''.join(states[n] for n in NAMES)
            result['reliable'] = '?' not in result['code']
            result['reason'] = 'edge_assisted_retracted_finger'
            result['evidence'] = 'unique_geometry_plus_new_interior_edge_three_frames'
        self.last_info = evidence
        return result

    def update(self, raw, palm, features, frame, reference):
        self.last_images = {}
        if frame is None or not palm.valid:
            self._clear_votes()
            if reference is None:
                self.baseline = None; self.baseline_count = 0; self.signature = None
            return self.fuse(raw, {}, False, 'no_valid_palm')
        patch, edges, middle_angle = self._normalize(frame, palm, raw, reference)
        self.last_images['palm_edges'] = edges
        if reference is None:
            self.baseline = None; self.baseline_count = 0; self.signature = None
            return self.fuse(raw, {}, False, 'no_identity_reference')
        base = reference.get('base_angles', reference['angles'])
        signature = tuple(float(x) for x in reference['calibration_center_xy']) + (float(reference['palm_radius_px']),) + tuple(float(x) for x in base)
        if signature != self.signature:
            self.baseline = None; self.baseline_count = 0; self._clear_votes(); self.signature = signature
        clear_open = (raw.get('reliable') and raw.get('code') == '1111' and
                      raw.get('matched_tip_count') == 5 and len(features.tips) == 5 and
                      features.info.get('valid') and features.info.get('valley_count', 0) >= 3)
        if self.baseline_count < 5:
            if clear_open:
                self.baseline = edges.copy() if self.baseline is None else cv2.bitwise_or(self.baseline, edges)
                self.baseline_count += 1
            else:
                self.baseline = None; self.baseline_count = 0
        ready = self.baseline_count >= 5
        fresh = np.zeros(edges.shape, np.uint8)
        if ready:
            previous = cv2.dilate(self.baseline, np.ones((5, 5), np.uint8))
            fresh = cv2.bitwise_and(edges, cv2.bitwise_not(previous))
        self.last_images['palm_new_edges'] = fresh
        overlay = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
        overlay[edges > 0] = (0, 210, 0)
        overlay[fresh > 0] = (0, 0, 255)
        self.last_images['palm_edge_overlay'] = overlay
        observations = {}
        if ready:
            for i, name in enumerate(NAMES):
                if raw['states'].get(name) == '?':
                    cap = self._cap(fresh, float(reference['angles'][i]) - middle_angle)
                    if cap is not None:
                        observations[name] = cap
        gate = 'eligible' if ready else 'learning_open_palm_edges'
        return self.fuse(raw, observations, ready, gate)
