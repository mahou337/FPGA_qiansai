"""Conservative geometric identity hypotheses and final-code debounce.

No learned model and no image rotation. Full five-tip geometry supplies a
calibrated anatomical reference; visible tip correspondence maintains it.
Count alone never determines identity.
"""
from compat_records import MISSING
from compat_cv import find_contours
from itertools import combinations, permutations
from compat_records import replace
from copy import deepcopy
from collections import deque
import cv2
import time
import numpy as np
from palm_motion import PalmMotionTracker
from finger_root_match import root_graph_hypotheses
FINGER_NAMES = ('Thumb', 'Index', 'Middle', 'Ring', 'Little')

def wrapped(angle):
    return (np.asarray(angle) + np.pi) % (2 * np.pi) - np.pi

def unknown(reason, tips=None):
    return {'states': {name: '?' for name in FINGER_NAMES[:4]}, 'code': '????', 'reliable': False, 'reason': reason, 'tip_identities': {}, 'reference_age': None, 'evidence': 'insufficient_geometry'}

def open_hand_order(tips):
    """Return anatomical order only if one end has a distinct thumb gap.

    This is a shape hypothesis, not guaranteed hand recognition. In particular
    five arbitrary hull vertices do not satisfy this check.
    """
    if len(tips) != 5 or any((tip['radius_ratio'] < 1.65 for tip in tips)):
        return None
    angles = np.array([tip['angle_rad'] for tip in tips])
    sorted_ids = np.argsort(angles)
    gaps = np.diff(np.r_[angles[sorted_ids], angles[sorted_ids[0]] + 2 * np.pi])
    cut = int(np.argmax(gaps))
    order = list(np.roll(sorted_ids, -cut - 1))
    fan = np.unwrap(angles[order])
    spread = float(fan[-1] - fan[0])
    if not np.deg2rad(65) <= spread <= np.deg2rad(190):
        return None
    internal = np.diff(fan)
    if internal[0] > max(np.deg2rad(25), 1.5 * internal[-1]):
        pass
    elif internal[-1] > max(np.deg2rad(25), 1.5 * internal[0]):
        order.reverse()
    else:
        return None
    if tips[order[0]]['radius_ratio'] >= 0.9 * max((tips[i]['radius_ratio'] for i in order[1:])):
        return None
    if sum((tips[i]['valley_support'] for i in order)) < 3:
        return None
    return [int(i) for i in order]

def boundary_contacts(palm):
    """Foreground edge pixels, preserving image coordinates and optional ROI."""
    mask = palm.mask
    h, w = mask.shape
    edge = np.zeros(mask.shape, np.uint8)
    edge[0] = mask[0]
    edge[-1] = mask[-1]
    edge[:, 0] = mask[:, 0]
    edge[:, -1] = mask[:, -1]
    roi = palm.info.get('active_roi_xywh')
    if roi is not None:
        x, y, rw, rh = roi
        x1, y1 = (max(0, x), max(0, y))
        x2, y2 = (min(w - 1, x + rw - 1), min(h - 1, y + rh - 1))
        if x1 <= x2 and y1 <= y2:
            edge[y1, x1:x2 + 1] = mask[y1, x1:x2 + 1]
            edge[y2, x1:x2 + 1] = mask[y2, x1:x2 + 1]
            edge[y1:y2 + 1, x1] = mask[y1:y2 + 1, x1]
            edge[y1:y2 + 1, x2] = mask[y1:y2 + 1, x2]
    yy, xx = np.nonzero(edge)
    if palm.center is None or not len(xx):
        return (np.array([]), np.array([]))
    dx, dy = (xx - palm.center[0], yy - palm.center[1])
    return (np.arctan2(dy, dx), np.hypot(dx, dy) / palm.radius)

def clipped_finger_slots(palm, angles):
    contacts, radii = boundary_contacts(palm)
    if not len(contacts):
        return set()
    affected = set()
    for slot, angle in enumerate(angles):
        gaps = np.abs(wrapped(np.asarray(angles) - angle))
        gaps = gaps[gaps > 1e-06]
        width = max(np.deg2rad(10), 0.5 * float(gaps.min())) if len(gaps) else np.deg2rad(15)
        if np.any((np.abs(wrapped(contacts - angle)) <= width) & (radii >= 0.65)):
            affected.add(slot)
    return affected

def measured_valley_pairs(palm, features):
    """Associate accepted valleys with their two actually observed tip endpoints."""
    pairs = []
    if len(features.tips) < 2:
        return pairs
    points = np.asarray([tip['xy'] for tip in features.tips], float)
    for defect in features.defects:
        if not defect.get('accepted'):
            continue
        ends = []
        for key in ('start_xy', 'end_xy'):
            distances = np.linalg.norm(points - np.asarray(defect[key]), axis=1)
            i = int(np.argmin(distances))
            if distances[i] > 0.65 * palm.radius:
                break
            ends.append(i)
        if len(ends) == 2 and ends[0] != ends[1]:
            pairs.append((ends[0], ends[1], (np.asarray(defect['valley_xy']) - palm.center) / palm.radius))
    return pairs

def feasible_assignments(ids, possible):
    """Yield exactly the feasible permutations in the old lexicographic order.

    Prune impossible prefixes instead of enumerating all 5! assignments and
    rejecting them. This does not loosen matching or ambiguity tolerances.
    """
    def visit(index, used, slots):
        if index == len(ids):
            yield tuple(slots)
            return
        for slot in possible[ids[index]]:
            if slot not in used:
                for result in visit(index + 1, used | {slot}, slots + [slot]):
                    yield result
    return visit(0, set(), [])

class GeometricClassifier:
    """Maintain calibrated slots while actual, uniquely matched tips remain visible.

    memory_frames counts frames without a validated observation, not time since
    all five fingers were open. A lone tip can only continue an established track;
    it never supplies a new rotation estimate for the other finger slots.
    """

    def __init__(self, memory_frames=45, single_tip_memory_frames=8):
        self.memory_frames = memory_frames
        self.single_tip_memory_frames = single_tip_memory_frames
        self.reset('startup')

    def reset(self, reason='manual'):
        self.last_reset_reason = reason
        self.reference = None
        self.age = self.full_age = self.anchor_age = 0
        self.last_center = None
        self.last_radius = None
        self.chirality = None
        self.single_anchor = None
        self.observed_radius = None
        self.active_scale = 1.0
        self.assignment_alternatives = []
        self._cached_track = None
        self.last_observed_mask = None
        self.last_raw_code = None
        self.valley_observations = []
        self.root_disputed_slots = set()
        self.root_supported_tip_ids = set()
        self.motion_pose_locked = False
        self.lowtip_tracking = False
        self.pair_pose_unverified = False
        self.root_graph_hypotheses = []
        self.root_graph_match = None
        self.working_center = None
        self.working_radius = None

    def _reference_snapshot(self):
        if self.reference is None:
            return {'mode': 'uncalibrated', 'observed_palm_radius_px': self.observed_radius, 'last_reset_reason': self.last_reset_reason}
        return {'mode': 'locked_calibration_radius', 'last_reset_reason': self.last_reset_reason, 'observed_palm_radius_px': self.observed_radius, 'normalization_radius_px': float(self.reference['palm_radius_px']), 'effective_normalization_radius_px': float(self.reference['palm_radius_px'] * self.active_scale), 'observed_scale': self.active_scale, 'calibration_center_xy': self.reference['calibration_center_xy'], 'reference_angles_rad': self.reference['angles'].tolist(), 'reference_tip_radius_ratios': self.reference['ratios'].tolist(), 'valley_anchors': self.reference.get('valley_anchors', []), 'distance_assumption': 'scale changes need at least three consistent long-finger observations'}

    def _unknown(self, reason, count=0):
        self.single_anchor = None
        result = unknown(reason)
        result.update(reference_age=self.age, full_reference_age=self.full_age, multi_tip_anchor_age=self.anchor_age, matched_tip_count=0, measured_tip_count=count, reference_refreshed=False, finger_evidence={})
        result['reference_geometry'] = self._reference_snapshot()
        return result

    @staticmethod
    def _extension_fraction(radius_ratio, calibrated_ratio):
        return float(max(0.0, radius_ratio - 1.0) / max(0.2, calibrated_ratio - 1.0))

    def _valley_agreement(self, ids, slots, rotation, valley_scale=1.0):
        assigned = dict(zip(ids, slots))
        anchors = self.reference.get('valley_anchors', [])
        if not anchors or len(self._current_tip_angles) != 2:
            return (0.0, set(), set())
        matrix = np.array([[np.cos(rotation), -np.sin(rotation)], [np.sin(rotation), np.cos(rotation)]])
        score, supported, disputed = (0.0, set(), set())
        for i, j, point in self.valley_observations:
            if i not in assigned or j not in assigned:
                continue
            # Folding an intervening finger creates a *new* valley. It is not
            # the adjacent web saved in the five-open reference. With a verified
            # palm pose and tight tip directions, do not use that new valley to
            # relabel the two surviving non-adjacent fingers.
            if (self.lowtip_tracking and self.motion_pose_locked and
                    abs(assigned[i] - assigned[j]) > 1 and
                    all(abs(float(wrapped(self._current_tip_angles[k] -
                        self.reference['angles'][assigned[k]] - rotation))) <= np.deg2rad(8)
                        for k in (i, j))):
                continue
            distances = [float(np.linalg.norm(point / valley_scale - matrix @ np.asarray(a['vector']))) for a in anchors]
            order = np.argsort(distances)
            best = anchors[int(order[0])]
            clear = distances[int(order[0])] <= 0.35 and (len(order) == 1 or distances[int(order[1])] - distances[int(order[0])] >= 0.15)
            pair = {assigned[i], assigned[j]}
            if clear:
                if pair == set(best['slots']):
                    if np.sign(float(wrapped(self._current_tip_angles[j] - self._current_tip_angles[i]))) == np.sign(float(wrapped(self.reference['angles'][assigned[j]] - self.reference['angles'][assigned[i]]))):
                        supported.update((i, j))
                        score += 0.3 * distances[int(order[0])] / 0.35
                else:
                    score += 1.0
                    disputed.update(pair.symmetric_difference(set(best['slots'])))
        return (score, supported, disputed)

    def _assign(self, tips, valley_scale=1.0):
        """Match extended tips; allow short bumps without forcing every peak into a slot."""
        ref = self.reference
        self.assignment_alternatives = []
        self.root_disputed_slots = set()
        self.root_supported_tip_ids = set()
        self.root_graph_match = None
        self.root_graph_hypotheses = []
        count = len(tips)
        if not count:
            return ((), (), 0.0, [])
        if count > 5:
            return None
        angles = np.array([tip['angle_rad'] for tip in tips])
        self._current_tip_angles = angles
        if self.working_center is not None and self.working_radius is not None and (valley_scale == 1.0):
            self.root_graph_hypotheses = root_graph_hypotheses(tips, self.valley_observations, ref, self.working_center, self.working_radius, self.active_scale)
            if self.lowtip_tracking and self.motion_pose_locked:
                # A graph fitted to a folded knuckle must not overrule a
                # verified image pose with an incompatible finger identity.
                self.root_graph_hypotheses = [g for g in self.root_graph_hypotheses
                    if all(abs(float(wrapped(angles[i] - ref['angles'][slot]))) <= np.deg2rad(25)
                           for i, slot in zip(g['indices'], g['slots']))]
            if len(self.root_graph_hypotheses) == 1:
                graph = self.root_graph_hypotheses[0]
                self.root_graph_match = graph
                self.root_supported_tip_ids = set(graph['indices'])
                return (graph['indices'], graph['slots'], 0.0, [])
        ratios = np.array([tip['radius_ratio'] for tip in tips])
        possible = []
        for i in range(count):
            possible.append([slot for slot in range(5) if self._extension_fraction(ratios[i], ref['ratios'][slot]) >= 0.9 and abs(np.log(ratios[i] / ref['ratios'][slot])) <= 0.25 and (abs(float(wrapped(angles[i] - ref['angles'][slot]))) <= np.deg2rad(47))])
        eligible = [i for i in range(count) if possible[i]]
        for kept in range(len(eligible), -1, -1):
            choices = []
            for ids in combinations(eligible, kept):
                for slots in feasible_assignments(ids, possible):
                    residual = wrapped(angles[list(ids)] - ref['angles'][list(slots)])
                    rotation = 0.0 if kept < 3 or self.motion_pose_locked else float(np.arctan2(np.sin(residual).mean(), np.cos(residual).mean()))
                    if abs(rotation) > np.deg2rad(35):
                        continue
                    errors = np.abs(wrapped(residual - rotation))
                    valley_cost, supported, _ = self._valley_agreement(ids, slots, rotation, valley_scale)
                    tolerances = np.array([np.deg2rad(24 if i in supported else 12) for i in ids])
                    if kept and np.any(errors > tolerances):
                        continue
                    rejected = []
                    for i in range(count):
                        if i in ids:
                            continue
                        gaps = np.abs(wrapped(angles[i] - ref['angles'] - rotation))
                        slot = int(np.argmin(gaps))
                        fraction = self._extension_fraction(ratios[i], ref['ratios'][slot])
                        if ratios[i] <= 1.35:
                            reason = 'palm_level_bump'
                        elif gaps[slot] <= np.deg2rad(15) and fraction < 0.9:
                            reason = 'short_bump_or_transition'
                        else:
                            break
                        rejected.append({'tip_index': i, 'nearest_finger': FINGER_NAMES[slot], 'extension_fraction': fraction, 'reason': reason})
                    else:
                        length_error = np.abs(np.log(ratios[list(ids)] / ref['ratios'][list(slots)])) if kept else np.array([0.0])
                        cost = float(np.mean(errors / tolerances)) if kept else 0.0
                        cost += float(length_error.mean() / 0.3 + 0.1 * abs(rotation) / np.deg2rad(35))
                        cost += valley_cost
                        choices.append((cost, ids, slots, rotation, rejected))
            choices.sort(key=lambda item: item[0])
            if choices:
                if len(choices) > 1 and choices[1][0] - choices[0][0] < 0.3:
                    self.assignment_alternatives = [item for item in choices if item[0] <= choices[0][0] + 0.3]
                    return None
                _, ids, slots, rotation, rejected = choices[0]
                self.root_disputed_slots = self._valley_agreement(ids, slots, rotation, valley_scale)[2]
                self.root_supported_tip_ids = self._valley_agreement(ids, slots, rotation, valley_scale)[1]
                return (ids, slots, rotation, rejected)
        return None

    def _coherent_scale_match(self, tips):
        """Adjust observation scale, never calibrated finger lengths.

        Require >=3 long fingers with common radial scaling. A lone shortened
        thumb/knuckle cannot supply a new scale or change its stored length.
        """
        if len(tips) < 3:
            return None
        ref = self.reference
        angles = np.array([tip['angle_rad'] for tip in tips])
        ratios = np.array([tip['radius_ratio'] for tip in tips])
        proposals = set()
        for ids in combinations(range(len(tips)), 3):
            for slots in permutations(range(1, 5), 3):
                residual = wrapped(angles[list(ids)] - ref['angles'][list(slots)])
                rotation = float(np.arctan2(np.sin(residual).mean(), np.cos(residual).mean()))
                if abs(rotation) > np.deg2rad(35) or np.max(np.abs(wrapped(residual - rotation))) > np.deg2rad(10):
                    continue
                factors = ratios[list(ids)] / ref['ratios'][list(slots)]
                factor = float(np.median(factors))
                if not 0.8 <= factor <= 1.2 or np.max(np.abs(np.log(factors / factor))) > 0.07:
                    continue
                if abs(np.log(factor)) < 0.025:
                    continue
                new_scale = self.active_scale * factor
                if not 0.75 <= new_scale <= 1.3:
                    continue
                body_scale = self.observed_radius / ref['palm_radius_px']
                if not 0.88 <= body_scale / new_scale <= 1.13:
                    continue
                proposals.add(round(factor, 4))
        groups = {}
        for factor in proposals:
            adjusted = [{**tip, 'radius_ratio': tip['radius_ratio'] / factor} for tip in tips]
            match = self._assign(adjusted, valley_scale=factor)
            if match is None:
                continue
            ids, slots, rotation, rejected = match
            long_pairs = [(i, s) for i, s in zip(ids, slots) if s != 0]
            if len(long_pairs) < 3:
                continue
            errors = np.abs(wrapped(angles[list(ids)] - ref['angles'][list(slots)] - rotation))
            lengths = np.abs(np.log(np.array([adjusted[i]['radius_ratio'] for i in ids]) / ref['ratios'][list(slots)]))
            score = float(errors.mean() / np.deg2rad(12) + lengths.mean() / 0.3 + 0.15 * abs(np.log(factor)))
            signature = tuple(zip(ids, slots))
            proposal = (score, factor, adjusted, match)
            if signature not in groups or score < groups[signature][0]:
                groups[signature] = proposal
        ranked = sorted(groups.values(), key=lambda item: (-len(item[3][0]), item[0]))
        if not ranked:
            return None
        if len(ranked) > 1 and len(ranked[1][3][0]) == len(ranked[0][3][0]) and (ranked[1][0] - ranked[0][0] < 0.3):
            return None
        factor, adjusted, _ = ranked[0][1:]
        match = self._assign(adjusted, valley_scale=factor)
        return None if match is None else (factor, adjusted, match)

    def _consensus_states(self, palm, tips, alternatives):
        """Preserve each finger's agreement across plausible assignments."""
        original = self.reference['angles'].copy()
        results = []
        for _, ids, slots, rotation, _ in alternatives:
            self.reference['angles'] = wrapped(original + rotation)
            states, evidence = self._states(palm, tips, slots, ids)
            results.append((states, evidence, dict(zip(ids, slots))))
        self.reference['angles'] = original
        states, evidence = ({}, {})
        for name in FINGER_NAMES[:4]:
            values = {item[0][name] for item in results}
            states[name] = next(iter(values)) if len(values) == 1 else '?'
            evidence[name] = {**results[0][1][name], 'state': states[name], 'reason': 'hypotheses_agree' if len(values) == 1 else 'finger_identity_ambiguous'}
        common = {i: s for i, s in results[0][2].items() if all((item[2].get(i) == s for item in results[1:]))}
        return {'states': states, 'code': ''.join((states[name] for name in FINGER_NAMES[:4])), 'reliable': False, 'reason': 'partial_finger_assignment', 'tip_identities': {str(i): FINGER_NAMES[s] for i, s in common.items()}, 'reference_age': self.age, 'full_reference_age': self.full_age, 'reference_refreshed': False, 'measured_tip_count': len(tips), 'matched_tip_count': len(common), 'finger_evidence': evidence, 'assignment_hypothesis_count': len(results), 'reference_geometry': self._reference_snapshot(), 'evidence': 'per_finger_consensus_no_new_command'}

    def _states(self, palm, tips, slots, tip_indices=None):
        ref = self.reference
        tip_indices = tuple(range(len(tips))) if tip_indices is None else tip_indices
        assigned = {slot: index for index, slot in zip(tip_indices, slots)}
        yy, xx = np.nonzero(palm.mask)
        pixel_angles = np.arctan2(yy - palm.center[1], xx - palm.center[0])
        pixel_radii = np.hypot(xx - palm.center[0], yy - palm.center[1]) / palm.radius
        states, evidence = ({}, {})
        clipped = clipped_finger_slots(palm, ref['angles'])
        for slot, name in enumerate(FINGER_NAMES[:4]):
            gaps = np.abs(wrapped(ref['angles'] - ref['angles'][slot]))
            gaps = gaps[gaps > 1e-06]
            half_width = min(np.deg2rad(8), 0.3 * float(gaps.min()))
            sector = np.abs(wrapped(pixel_angles - ref['angles'][slot])) <= half_width
            excluded_neighbor = False
            if slot not in assigned:
                for other_slot, index in assigned.items():
                    if index not in self.root_supported_tip_ids:
                        continue
                    tip = tips[index]
                    vector = np.array([np.cos(tip['angle_rad']), np.sin(tip['angle_rad'])])
                    along = ((xx - palm.center[0]) * vector[0] + (yy - palm.center[1]) * vector[1]) / palm.radius
                    across = np.abs(-(xx - palm.center[0]) * vector[1] + (yy - palm.center[1]) * vector[0]) / palm.radius
                    tube = (along > 1.25) & (along < tip['radius_ratio'] + 0.15) & (across < 0.5 * tip.get('width_ratio', 0.4) + 0.12)
                    if np.any(sector & tube):
                        sector = sector & ~tube
                        excluded_neighbor = True
            sector_extent = float(pixel_radii[sector].max()) if np.any(sector) else 0.0
            nearby = [tip['radius_ratio'] for i, tip in enumerate(tips) if not (slot not in assigned and i in self.root_supported_tip_ids and (i in assigned.values())) and int(np.argmin(np.abs(wrapped(ref['angles'] - tip['angle_rad'])))) == slot and (abs(float(wrapped(tip['angle_rad'] - ref['angles'][slot]))) <= np.deg2rad(15))]
            extent = max([sector_extent] + nearby)
            fraction = self._extension_fraction(extent, float(ref['ratios'][slot]))
            folded_limit = 1.0 + 0.7 * max(0.2, float(ref['ratios'][slot]) - 1.0)
            if slot in clipped:
                state, reason = ('?', 'finger_sector_reaches_image_or_roi_border')
            elif slot in assigned:
                state, reason = ('1', 'matched_tip_reaches_calibrated_extension')
            elif 0 < extent and fraction <= 0.7:
                state, reason = ('0', 'calibrated_sector_retracted')
            else:
                state, reason = ('?', 'tip_absent_but_sector_not_retracted')
            states[name] = state
            evidence[name] = {'state': state, 'reason': reason, 'sector_extent_over_radius': sector_extent, 'observed_extent_over_radius': extent, 'extension_fraction': fraction, 'folded_fraction_max': 0.7, 'extended_fraction_min': 0.9, 'folded_limit_over_radius': folded_limit, 'calibrated_tip_over_radius': float(ref['ratios'][slot]), 'sector_half_width_degrees': float(np.degrees(half_width)), 'verified_neighbor_projection_excluded': excluded_neighbor, 'image_or_roi_edge_intersects_sector': slot in clipped, 'measured_tip_index': assigned.get(slot)}
        return (states, evidence)

    def classify(self, palm, features):
        cached = None
        if not palm.valid:
            if palm.info.get('reasons') == ['no_region']:
                if self.reference is not None and self.last_center is not None:
                    cached = {'reference': deepcopy(self.reference), 'scale': self.active_scale, 'center': self.last_center.copy(), 'chirality': self.chirality, 'age': self.age, 'full_age': self.full_age, 'remaining': 3}
                elif self._cached_track is not None:
                    cached = deepcopy(self._cached_track)
                    cached['remaining'] -= 1
                    if cached['remaining'] <= 0:
                        cached = None
            result = self._classify(palm, features)
            self._cached_track = cached
            result['reference_geometry']['cache_remaining_frames'] = 0 if cached is None else cached['remaining']
            return result
        recovering = False
        if self.reference is None and self._cached_track is not None:
            cached = self._cached_track
            radius = cached['reference']['palm_radius_px'] * cached['scale']
            if np.linalg.norm(np.asarray(palm.center) - cached['center']) <= 0.6 * radius:
                self.reference = deepcopy(cached['reference'])
                self.active_scale = cached['scale']
                self.chirality = cached['chirality']
                self.last_center = cached['center'].copy()
                self.last_radius = radius
                self.age = cached['age'] + 1
                self.full_age = cached['full_age'] + 1
                recovering = True
            self._cached_track = None
        result = self._classify(palm, features)
        if recovering:
            if result.get('matched_tip_count', 0) >= 3 and result.get('reference_refreshed'):
                result['reference_reacquired'] = True
                result['reason'] = 'reacquired_from_three_visible_fingers'
            else:
                self.reset('dropout_reacquisition_failed')
                result = self._unknown('reacquire_requires_three_visible_fingers', len(features.tips))
        self.last_observed_mask = palm.mask.copy()
        self.last_raw_code = result['code']
        return result

    def _classify(self, palm, features):
        if not palm.valid:
            reason = 'palm_invalid:' + ','.join(palm.info.get('reasons', [])) if self.reference is not None else self.last_reset_reason
            self.reset(reason)
            return self._unknown('invalid_or_missing_region')
        observed_palm, observed_features = (palm, features)
        self.observed_radius = float(palm.radius)
        if self.reference is not None:
            anchor_radius = self.reference['palm_radius_px'] * self.active_scale
            if not 0.6 <= palm.radius / anchor_radius <= 1.65:
                self.age += 1
                self.anchor_age += 1
                self.full_age += 1
                return self._unknown('palm_geometry_or_distance_changed', len(features.tips))
            multiplier = palm.radius / anchor_radius
            palm = replace(palm, radius=anchor_radius)
            features = replace(features, tips=[{**tip, 'radius_ratio': tip['radius_ratio'] * multiplier} for tip in features.tips])
        center = np.asarray(palm.center)
        center_step = 0.0 if self.last_center is None else float(np.linalg.norm(center - self.last_center) / palm.radius)
        scale_step = 1.0 if self.last_radius is None else palm.radius / self.last_radius
        if self.last_center is not None and (center_step > 2 or not 0.6 <= scale_step <= 1.65):
            self.reset('large_geometry_jump' if self.reference is not None else self.last_reset_reason)
            palm, features = (observed_palm, observed_features)
            self.observed_radius = float(palm.radius)
        self.last_center, self.last_radius = (center.copy(), palm.radius)
        count = len(features.tips)
        _, contact_radii = boundary_contacts(palm)
        palm_cut = bool(len(contact_radii) and contact_radii.min() < 0.65)
        if not features.info['valid'] or palm_cut:
            self.age += 1
            self.anchor_age += 1
            self.full_age += 1
            return self._unknown('clipped_or_unreliable_contour', count)
        tips = features.tips
        self.working_center = np.asarray(palm.center, float)
        self.working_radius = palm.radius
        self.valley_observations = measured_valley_pairs(palm, features)
        order = open_hand_order(tips)
        if self.reference is None and order is not None and (features.info['valley_count'] >= 3):
            angles = np.array([tips[i]['angle_rad'] for i in order])
            if clipped_finger_slots(palm, angles):
                return self._unknown('finger_region_clipped_during_calibration', count)
            chirality = int(np.sign(float(wrapped(angles[1] - angles[0]))))
            replaced = self.chirality is not None and chirality != self.chirality
            self.chirality = chirality
            self.reference = {'angles': angles, 'ratios': np.array([tips[i]['radius_ratio'] for i in order]), 'palm_radius_px': float(palm.radius), 'calibration_center_xy': [int(v) for v in palm.center]}
            self.reference['valley_anchors'] = [{'slots': sorted((order.index(i), order.index(j))), 'vector': point.tolist()} for i, j, point in self.valley_observations]
            self.reference['base_angles'] = angles.copy()
            self.reference['base_valley_anchors'] = deepcopy(self.reference['valley_anchors'])
            self.age = self.full_age = self.anchor_age = 0
            self.single_anchor = None
            slots = [order.index(i) for i in range(5)]
            states, evidence = self._states(palm, tips, slots)
            return {'states': states, 'code': '1111', 'reliable': True, 'reason': 'five_tip_anatomical_hypothesis', 'tip_identities': {str(i): name for i, name in zip(order, FINGER_NAMES)}, 'reference_age': 0, 'full_reference_age': 0, 'multi_tip_anchor_age': 0, 'reference_replaced': replaced, 'reference_refreshed': True, 'calibration_locked': True, 'rejected_tip_candidates': [], 'measured_tip_count': 5, 'matched_tip_count': 5, 'finger_evidence': evidence, 'reference_geometry': self._reference_snapshot(), 'evidence': 'thumb_gap_plus_five_tips_and_valleys'}
        if self.reference is not None and order is not None:
            observed = np.array([tips[i]['angle_rad'] for i in order])
            chirality = int(np.sign(float(wrapped(observed[1] - observed[0]))))
            if chirality != self.chirality:
                return self._unknown('hand_changed_press_K_and_show_open_hand', count)
        self.age += 1
        self.full_age += 1
        self.anchor_age += 1
        if self.reference is None:
            return self._unknown('show_full_open_hand_to_establish_identity_reference', count)
        expired = self.age > self.memory_frames
        match = self._assign(tips)
        alternatives = self.assignment_alternatives.copy()
        if not self.motion_pose_locked and (match is None or sum((slot != 0 for slot in match[1])) < 3):
            adjustment = self._coherent_scale_match(tips)
            if adjustment is not None:
                factor, tips, match = adjustment
                self.active_scale *= factor
                palm = replace(palm, radius=palm.radius * factor)
                self.last_radius = palm.radius
                features = replace(features, tips=tips)
        if match is None:
            if alternatives:
                return self._consensus_states(palm, tips, alternatives)
            if expired:
                return self._unknown('identity_track_lost_show_open_hand', count)
            return self._unknown('ambiguous_finger_assignment', count)
        tip_indices, slots, rotation, rejected = match
        matched_count = len(slots)
        if self.lowtip_tracking and self.pair_pose_unverified and 0 < matched_count <= 2:
            return self._unknown('low_tip_identity_requires_verified_pose', count)
        if count == 2 and self.pair_pose_unverified and (self.root_graph_match is None):
            return self._unknown('two_finger_identity_needs_palm_motion', count)
        if expired and matched_count < 3 and (not self.motion_pose_locked) and (self.root_graph_match is None):
            return self._unknown('identity_track_lost_show_open_hand', count)
        single_vector = None
        if matched_count == 1:
            tip = tips[tip_indices[0]]
            single_vector = tip['radius_ratio'] * np.array([np.cos(tip['angle_rad']), np.sin(tip['angle_rad'])])
            continuous = self.single_anchor is not None and slots[0] == self.single_anchor['slot'] and (np.linalg.norm(single_vector - self.single_anchor['vector']) <= 0.2) and (center_step <= 0.6) and (0.85 <= scale_step <= 1.18)
            if self.anchor_age > self.single_tip_memory_frames and (not continuous) and (not self.motion_pose_locked):
                return self._unknown('single_tip_continuity_lost_show_open_hand', count)
        if matched_count >= 2 and (not self.root_disputed_slots):
            self.reference['angles'] = wrapped(self.reference['angles'] + rotation)
            matrix = np.array([[np.cos(rotation), -np.sin(rotation)], [np.sin(rotation), np.cos(rotation)]])
            for anchor in self.reference.get('valley_anchors', []):
                anchor['vector'] = (matrix @ np.asarray(anchor['vector'])).tolist()
        if self.lowtip_tracking and not slots and any(
                t['radius_ratio'] > 1.6 and t.get('width_ratio', 1.0) <= 0.55
                and t.get('curvature_degrees', 180) <= 90 for t in tips):
            return self._unknown('shortened_straight_tip_not_a_verified_fist', count)
        states, evidence = self._states(palm, tips, slots, tip_indices)
        if self.root_graph_match is not None:
            for slot in slots:
                if slot < 4 and states[FINGER_NAMES[slot]] == '1':
                    evidence[FINGER_NAMES[slot]]['reason'] = 'unique_finger_root_length_graph'
        for slot in self.root_disputed_slots:
            if slot < 4:
                states[FINGER_NAMES[slot]] = '?'
                evidence[FINGER_NAMES[slot]]['state'] = '?'
                evidence[FINGER_NAMES[slot]]['reason'] = 'valley_conflicts_with_tip_assignment'
        if self.root_disputed_slots:
            matched_count = sum((slot not in self.root_disputed_slots for slot in slots))
        code = ''.join((states[name] for name in FINGER_NAMES[:4]))
        refreshed = False
        if matched_count >= 2:
            self.age = self.anchor_age = 0
            self.single_anchor = None
            refreshed = True
        elif matched_count == 1 and '?' not in code:
            self.single_anchor = {'slot': slots[0], 'vector': single_vector.copy()}
            self.age = 0
            refreshed = True
        else:
            self.single_anchor = None
        body_continuity = False
        if matched_count == 0 and code == '0000' and (self.last_raw_code == '0000') and (self.last_observed_mask is not None):
            if self.last_observed_mask.shape == palm.mask.shape and center_step <= 0.35:
                union = np.count_nonzero((self.last_observed_mask > 0) | (palm.mask > 0))
                overlap = np.count_nonzero((self.last_observed_mask > 0) & (palm.mask > 0)) / max(1, union)
                body_continuity = overlap >= 0.7
                if body_continuity:
                    self.age = 0
                    refreshed = True
        return {'states': states, 'code': code, 'reliable': '?' not in code, 'reason': 'tracked_finger_states' if '?' not in code else 'unobserved_or_merged_finger', 'tip_identities': {str(index): FINGER_NAMES[slot] for index, slot in zip(tip_indices, slots)}, 'reference_age': self.age, 'full_reference_age': self.full_age, 'multi_tip_anchor_age': self.anchor_age, 'reference_refreshed': refreshed, 'measured_tip_count': count, 'matched_tip_count': len(slots), 'finger_evidence': evidence, 'rejected_tip_candidates': rejected, 'calibration_locked': True, 'reference_reacquired': expired and (matched_count >= 3 or self.motion_pose_locked or self.root_graph_match is not None), 'finger_root_graph_match': self.root_graph_match, 'closed_pose_continuity': body_continuity, 'reference_geometry': self._reference_snapshot(), 'evidence': 'calibrated_slots_with_visible_tip_correspondence_and_sector_retraction'}

class GestureDebouncer:

    def __init__(self, confirm_frames=1, hold_frames=0):
        self.confirm_frames, self.hold_frames = (confirm_frames, hold_frames)
        self.reset()

    def reset(self):
        self.stable = None
        self.pending = None
        self.count = self.unknown_count = 0

    def update(self, raw, hand_present):
        command_ready = False
        if not hand_present:
            self.reset()
            status = 'NO HAND'
        elif raw.get('reference_replaced') or raw.get('reference_reacquired'):
            self.reset()
            status = 'PENDING'
        else:
            status = 'UNKNOWN'
        if hand_present and raw['reliable']:
            self.unknown_count = 0
            if raw['code'] == self.pending:
                self.count += 1
            else:
                self.pending, self.count = (raw['code'], 1)
            if self.count >= self.confirm_frames:
                command_ready = raw['code'] != self.stable
                self.stable = raw['code']
                status = 'CONFIRMED'
            else:
                status = 'PENDING'
        elif hand_present:
            self.pending, self.count = (None, 0)
            self.unknown_count += 1
            if self.stable is not None and self.unknown_count <= self.hold_frames:
                status = 'HOLD'
            else:
                self.stable = None
                status = 'UNKNOWN'
        partial = hand_present and raw['code'] != '????' and ('?' in raw['code'])
        if partial:
            status = 'PARTIAL'
        elif hand_present and raw['reason'] == 'show_full_open_hand_to_establish_identity_reference':
            status = 'NEED CALIBRATION'
        elif hand_present and raw['reason'] == 'identity_track_lost_show_open_hand':
            status = 'REACQUIRE'
        code = raw['code'] if partial else self.stable if self.stable is not None else '????'
        states = dict(zip(FINGER_NAMES[:4], code))
        return {'raw': raw, 'states': states, 'code': code, 'status': status, 'reliable': status == 'CONFIRMED', 'command_ready': command_ready, 'confirm_count': self.count, 'unknown_count': self.unknown_count, 'stable_code': self.stable, 'unknown_fingers': [name for name in FINGER_NAMES[:4] if raw['states'][name] == '?']}

class GesturePipeline:

    def __init__(self, confirm_frames=1, hold_frames=0, memory_frames=45, reset_reason='startup'):
        self.classifier = GeometricClassifier(memory_frames=memory_frames)
        if reset_reason != 'startup':
            self.classifier.reset(reset_reason)
        self.debouncer = GestureDebouncer(confirm_frames, hold_frames)
        self.motion = PalmMotionTracker()
        self.lowtip_tracking = False
        self.reseed_candidate = None
        self.reseed_count = 0
        self.motion_enabled = True
        self.motion_ever_valid = False
        self.motion_mask_gap = 0
        self.frame_index = 0
        self.history = deque(maxlen=45)
        self.edge_assist = None
        self.last_edge_ms = 0.0

    def _seed_motion(self, frame, palm, features, raw, new_reference):
        ref = self.classifier.reference
        names = raw.get('tip_identities', {})
        full_open = len(features.tips) == 5 and raw.get('code') == '1111'
        long_count = sum(name != 'Thumb' for name in names.values())
        multi = (self.lowtip_tracking and long_count >= 3 and
                 features.info.get('valley_count', 0) >= 2)
        if ref is None or not raw.get('reliable') or not (full_open or multi):
            self.reseed_candidate = None
            self.reseed_count = 0
            return
        if not full_open:
            key = tuple(sorted(names.values()))
            self.reseed_count = self.reseed_count + 1 if key == self.reseed_candidate else 1
            self.reseed_candidate = key
            if self.reseed_count < 3:
                return
        self.motion.middle_angle = float(ref.get('base_angles', ref['angles'])[2])
        if new_reference and full_open:
            pose = self.motion.initialize(frame, palm)
        else:
            base = ref.get('base_angles', ref['angles'])
            center = np.asarray(ref['calibration_center_xy'], float)
            source_all = center + ref['palm_radius_px'] * ref['ratios'][:, None] * np.column_stack((np.cos(base), np.sin(base)))
            if len(names) < (5 if full_open else 3):
                return
            pairs = sorted((int(i), FINGER_NAMES.index(name)) for i, name in names.items())
            source = np.asarray([source_all[slot] for i, slot in pairs], np.float32)
            target = np.asarray([features.tips[i]['xy'] for i, slot in pairs], np.float32)
            transform, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                                           ransacReprojThreshold=4.0 if full_open else 2.0)
            if transform is None or inliers.sum() < (4 if full_open else len(pairs)):
                return
            residual = np.linalg.norm(source @ transform[:, :2].T + transform[:, 2] - target, axis=1)
            if np.median(residual) > 3.0 or (not full_open and residual.max() > 2.0):
                return
            scale = float(np.hypot(transform[0, 0], transform[1, 0]))
            predicted_center = transform[:, :2] @ center + transform[:, 2]
            x, y = np.rint(predicted_center).astype(int)
            if not full_open and (not 0.6 <= scale <= 1.6 or
                    not (0 <= x < palm.mask.shape[1] and 0 <= y < palm.mask.shape[0]) or
                    palm.mask[y, x] == 0 or np.linalg.norm(predicted_center - palm.center) > 1.2 * palm.radius):
                return
            pose = self.motion.initialize(frame, palm, center, ref['palm_radius_px'], transform)
            if not full_open:
                raw['motion_reseed_from_three_long_fingers'] = bool(pose.get('valid'))
        self.motion_ever_valid = self.motion_ever_valid or pose.get('valid', False)

    def update(self, palm, features, frame=None):
        self.frame_index += 1
        self.last_edge_ms = 0.0
        c = self.classifier
        c.lowtip_tracking = self.lowtip_tracking
        had_reference = c.reference is not None
        pose = {'valid': False, 'reason': 'no_frame_or_disabled'}
        used = False
        classification_palm, classification_features = (palm, features)
        if frame is not None and self.motion_enabled:
            pose = self.motion.update(frame, palm.mask if palm.valid else None)
            if pose.get('valid') and had_reference:
                if not palm.valid:
                    self.motion_mask_gap += 1
                    if self.motion_mask_gap <= 15:
                        c.age += 1
                        raw = c._unknown('mask_missing_but_palm_image_tracked', len(features.tips))
                        raw['palm_motion'] = pose
                        if self.edge_assist is not None:
                            edge_start = time.perf_counter()
                            raw = self.edge_assist.update(raw, palm, features, frame, c.reference)
                            self.last_edge_ms = (time.perf_counter() - edge_start) * 1000
                        result = self.debouncer.update(raw, False)
                        self.history.append({'frame': self.frame_index, 'code': raw['code'], 'reason': raw['reason'], 'motion': pose['reason']})
                        result['recent_decisions'] = list(self.history)
                        return result
                    c.reset('tracked_image_mask_gap_timeout')
                    self.motion.clear()
                    had_reference = False
                else:
                    center = np.asarray(pose['center_xy'])
                    xy = np.rint(center).astype(int)
                    inside = 0 <= xy[0] < palm.mask.shape[1] and 0 <= xy[1] < palm.mask.shape[0] and (palm.mask[xy[1], xy[0]] > 0)
                    if inside and 0.6 <= palm.radius / pose['radius_px'] <= 1.65:
                        ref = c.reference
                        rotation = pose['rotation_rad']
                        base = ref.get('base_angles', ref['angles'])
                        ref['angles'] = wrapped(base + rotation)
                        matrix = np.array([[np.cos(rotation), -np.sin(rotation)], [np.sin(rotation), np.cos(rotation)]])
                        ref['valley_anchors'] = [{'slots': a['slots'], 'vector': (matrix @ np.asarray(a['vector'])).tolist()} for a in ref.get('base_valley_anchors', ref.get('valley_anchors', []))]
                        c.active_scale = pose['scale']
                        classification_palm = replace(palm, center=tuple(center), radius=pose['radius_px'])
                        tips = []
                        for tip in features.tips:
                            delta = np.asarray(tip['xy'], float) - center
                            tips.append({**tip, 'radius_ratio': float(np.linalg.norm(delta) / pose['radius_px']), 'angle_rad': float(np.arctan2(delta[1], delta[0])), 'width_ratio': tip.get('width_ratio', 0.4) * palm.radius / pose['radius_px']})
                        classification_features = replace(features, tips=tips)
                        if self.lowtip_tracking and features.info.get('valid'):
                            from finger_detection import detect_fingers
                            classification_features = detect_fingers(classification_palm,
                                separate_close_tips=True)
                        used = True
        self.classification_features = classification_features
        if used:
            self.reseed_candidate = None
            self.reseed_count = 0
        c.motion_pose_locked = used
        c.pair_pose_unverified = self.motion_enabled and self.motion_ever_valid and (frame is not None) and (not used)
        raw = c.classify(classification_palm, classification_features)
        if used and self.motion_mask_gap:
            raw['reference_reacquired'] = True
        self.motion_mask_gap = 0
        if frame is not None and self.motion_enabled and (not used):
            self._seed_motion(frame, palm, features, raw, not had_reference)
            if self.motion.last.get('reason') == 'initialized':
                pose = dict(self.motion.last)
        raw['palm_motion'] = {**pose, 'used_for_identity': used, 'native_center_xy': palm.center, 'native_radius_px': palm.radius}
        raw['reference_geometry']['observed_palm_radius_px'] = palm.radius
        if self.edge_assist is not None:
            edge_start = time.perf_counter()
            raw = self.edge_assist.update(raw, classification_palm, classification_features, frame, c.reference)
            self.last_edge_ms = (time.perf_counter() - edge_start) * 1000
        result = self.debouncer.update(raw, palm.valid)
        self.history.append({'frame': self.frame_index, 'code': raw['code'], 'reason': raw['reason'], 'motion': pose['reason'], 'motion_used': used, 'identities': raw['tip_identities'], 'native_palm_center_xy': palm.center, 'tracked_palm_center_xy': pose.get('center_xy'), 'tracked_point_count': pose.get('point_count', 0), 'motion_fit_error_px': pose.get('reprojection_error_px'), 'tip_xy': [tip['xy'] for tip in features.tips], 'root_graph_slots': (raw.get('finger_root_graph_match') or {}).get('slots')})
        result['recent_decisions'] = list(self.history)
        return result
