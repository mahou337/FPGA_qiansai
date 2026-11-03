from compat_records import MISSING
from compat_cv import find_contours
from collections import OrderedDict
'Translation-invariant fingertip/valley graph matching against an open-hand reference.'
from itertools import permutations
import numpy as np

def root_graph_hypotheses(tips, observed_edges, reference, center, radius, observed_scale=1.0):
    count = len(tips)
    if count not in (2, 3) or not observed_edges:
        return []
    covered = set()
    edges = []
    for i, j, point in observed_edges:
        covered.update((i, j))
        edges.append((i, j, np.asarray(center) + radius * np.asarray(point)))
    if len(covered) != count:
        return []
    cal_radius = float(reference['palm_radius_px'])
    angles = reference['angles']
    cal_tips = cal_radius * reference['ratios'][:, None] * np.column_stack((np.cos(angles), np.sin(angles)))
    anchors = {frozenset(a['slots']): cal_radius * np.asarray(a['vector']) for a in reference.get('valley_anchors', [])}
    points = np.asarray([tip['xy'] for tip in tips], float)
    accepted = []
    tolerance = 0.14 if count == 2 else 0.22
    for slots in permutations(range(5), count):
        factors = []
        errors = []
        observed_lengths = []
        rotations = []
        for i, j, root in edges:
            anchor = anchors.get(frozenset((slots[i], slots[j])))
            if anchor is None:
                break
            a, b = (points[i] - root, points[j] - root)
            ca, cb = (cal_tips[slots[i]] - anchor, cal_tips[slots[j]] - anchor)
            lengths = np.array([np.linalg.norm(a), np.linalg.norm(b)])
            cal_lengths = np.array([np.linalg.norm(ca), np.linalg.norm(cb)])
            if min(lengths) < 2 or min(cal_lengths) < 2:
                break
            observed_cross = a[0] * b[1] - a[1] * b[0]
            cal_cross = ca[0] * cb[1] - ca[1] * cb[0]
            if observed_cross * cal_cross <= 0:
                break
            if abs(observed_cross) / np.prod(lengths) < 0.08:
                break
            delta = (np.array([np.arctan2(a[1], a[0]) - np.arctan2(ca[1], ca[0]), np.arctan2(b[1], b[0]) - np.arctan2(cb[1], cb[0])]) + np.pi) % (2 * np.pi) - np.pi
            spread = float((delta[0] - delta[1] + np.pi) % (2 * np.pi) - np.pi)
            if abs(spread) > np.deg2rad(25):
                break
            rotations.extend(delta.tolist())
            pair_factors = lengths / cal_lengths
            error = abs(float(np.log(pair_factors[0] / pair_factors[1])))
            if error > tolerance:
                break
            factors.extend(pair_factors.tolist())
            observed_lengths.extend(lengths.tolist())
            errors.append(error)
        else:
            rotation = float(np.arctan2(np.sin(rotations).mean(), np.cos(rotations).mean()))
            if abs(rotation) > np.deg2rad(35):
                continue
            residual = (np.asarray(rotations) - rotation + np.pi) % (2 * np.pi) - np.pi
            if np.max(np.abs(residual)) > np.deg2rad(20):
                continue
            scale = float(np.median(factors))
            if not 0.75 <= scale <= 1.35:
                continue
            if not 0.9 <= scale / observed_scale <= 1.25:
                continue
            if np.max(np.abs(np.log(np.array(factors) / scale))) > 0.2:
                continue
            if min(observed_lengths) < 0.55 * cal_radius * scale:
                continue
            accepted.append({'indices': tuple(range(count)), 'slots': slots, 'implied_scale': scale, 'relative_length_residual': float(np.mean(errors)), 'source': 'observed_tip_to_valley_lengths_angles_and_order'})
    unique = OrderedDict(((item['slots'], item) for item in accepted))
    return list(unique.values())
