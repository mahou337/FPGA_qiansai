"""Classical palm-image feature tracking; no image rotation/normalization or learned model."""
from compat_records import MISSING
from compat_cv import find_contours
import cv2
import numpy as np

class PalmMotionTracker:

    def __init__(self, recoverable=False):
        self.recoverable = recoverable
        self.middle_angle = None
        self.clear()

    def clear(self):
        self.failed_frames = 0
        self.previous = None
        self.points = None
        self.reference_points = None
        self.center = None
        self.radius = None
        self.matrix = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.last = {'valid': False, 'reason': 'not_initialized'}

    @staticmethod
    def gray(frame):
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def _roi(self, shape, mask, center, radius):
        roi = np.zeros(shape, np.uint8)
        roi_center = np.asarray(center, float)
        if self.recoverable and self.middle_angle is not None:
            rotation = float(np.arctan2(self.matrix[1, 0], self.matrix[0, 0]))
            angle = self.middle_angle + rotation
            roi_center = roi_center - 0.35 * radius * np.array([np.cos(angle), np.sin(angle)])
        cv2.circle(roi, tuple(np.rint(roi_center).astype(int)), max(3, int(radius)), 255, -1)
        interior = cv2.erode(mask, np.ones((13, 13), np.uint8), iterations=1)
        return cv2.bitwise_and(roi, interior)

    def initialize(self, frame, palm, base_center=None, base_radius=None, initial_transform=None):
        self.clear()
        gray = self.gray(frame)
        center = np.asarray(palm.center if base_center is None else base_center, float)
        radius = float(palm.radius if base_radius is None else base_radius)
        transform = self.matrix if initial_transform is None else np.asarray(initial_transform, float)
        scale = float(np.hypot(transform[0, 0], transform[1, 0]))
        current_center = transform[:, :2] @ center + transform[:, 2]
        self.matrix = transform
        roi = self._roi(gray.shape, palm.mask, current_center, radius * scale)
        points = cv2.goodFeaturesToTrack(gray, maxCorners=80, qualityLevel=0.015, minDistance=3, mask=roi, blockSize=3)
        if points is None or len(points) < 8:
            self.last = {'valid': False, 'reason': 'too_few_palm_texture_points', 'point_count': 0 if points is None else len(points)}
            return self.last
        self.previous = gray
        self.points = points.astype(np.float32)
        origin = (self.points.reshape(-1, 2) - transform[:, 2]) @ np.linalg.inv(transform[:, :2]).T
        self.reference_points = origin.astype(np.float32).reshape(-1, 1, 2)
        self.center = center
        self.radius = radius
        self.matrix = transform
        self.last = {'valid': True, 'reason': 'initialized', 'point_count': len(points), 'center_xy': current_center.tolist(), 'radius_px': radius * scale, 'scale': scale, 'rotation_rad': float(np.arctan2(transform[1, 0], transform[0, 0])), 'reprojection_error_px': 0.0}
        return self.last

    def _fail(self, reason, **stats):
        # Retain the last *verified* image briefly, never return its old pose.
        # New frames must pass every LK/NCC/RANSAC gate before recovery.
        self.failed_frames += 1
        retry = self.recoverable and self.previous is not None and self.failed_frames <= 3 and reason != 'resolution_changed'
        if not retry:
            self.clear()
        self.last = {'valid': False, 'reason': reason, 'retry_reference_retained': retry, **stats}
        return self.last

    def update(self, frame, mask=None):
        if self.previous is None:
            return self.last
        gray = self.gray(frame)
        if gray.shape != self.previous.shape:
            return self._fail('resolution_changed')
        nxt, ok, error = cv2.calcOpticalFlowPyrLK(self.previous, gray, self.points, None, winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        if nxt is None or ok is None:
            return self._fail('forward_flow_failed')
        back, back_ok, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, nxt, None, winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        if back is None or back_ok is None:
            return self._fail('backward_flow_failed')
        fb = np.linalg.norm(back.reshape(-1, 2) - self.points.reshape(-1, 2), axis=1)
        valid = (ok.ravel() > 0) & (back_ok.ravel() > 0) & (fb < 1.0)
        correlations = []
        for i in np.flatnonzero(valid):
            before = cv2.getRectSubPix(self.previous, (9, 9), tuple(map(float, self.points[i, 0]))).astype(float).ravel()
            after = cv2.getRectSubPix(gray, (9, 9), tuple(map(float, nxt[i, 0]))).astype(float).ravel()
            before -= before.mean()
            after -= after.mean()
            denominator = float(np.linalg.norm(before) * np.linalg.norm(after))
            correlation = float(np.dot(before, after) / denominator) if denominator > 1e-06 else 0.0
            correlations.append(correlation)
            if correlation < 0.6:
                valid[i] = False
        src = self.reference_points[valid].reshape(-1, 2)
        dst = nxt[valid].reshape(-1, 2)
        minimum = 8
        if len(src) < minimum:
            return self._fail('too_few_appearance_verified_tracks', point_count=len(src))
        transform, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=1.8, maxIters=500, confidence=0.99, refineIters=10)
        if transform is None:
            return self._fail('motion_fit_failed')
        inlier = inliers.ravel() > 0
        if inlier.sum() < minimum or inlier.mean() < 0.6:
            return self._fail('motion_fit_inconsistent', point_count=int(inlier.sum()))
        predicted = src @ transform[:, :2].T + transform[:, 2]
        rms = float(np.sqrt(np.mean(np.sum((predicted[inlier] - dst[inlier]) ** 2, axis=1))))
        scale = float(np.hypot(transform[0, 0], transform[1, 0]))
        rotation = float(np.arctan2(transform[1, 0], transform[0, 0]))
        prior_scale = float(np.hypot(self.matrix[0, 0], self.matrix[1, 0]))
        prior_rotation = float(np.arctan2(self.matrix[1, 0], self.matrix[0, 0]))
        delta_rotation = (rotation - prior_rotation + np.pi) % (2 * np.pi) - np.pi
        center = transform[:, :2] @ self.center + transform[:, 2]
        prior_center = self.matrix[:, :2] @ self.center + self.matrix[:, 2]
        if rms > 1.5 or not 0.6 <= scale <= 1.6 or (not 0.9 <= scale / prior_scale <= 1.1):
            return self._fail('motion_scale_or_residual_rejected', reprojection_error_px=rms)
        if abs(delta_rotation) > np.deg2rad(15) or np.linalg.norm(center - prior_center) > 1.5 * self.radius * prior_scale:
            return self._fail('motion_jump_rejected')
        span = np.ptp(dst[inlier], axis=0)
        if span.min() < 0.25 * self.radius * scale:
            return self._fail('motion_points_too_concentrated')
        coverage = None
        if mask is not None and np.any(mask):
            xy = np.rint(dst[inlier]).astype(int)
            inside = (xy[:, 0] >= 0) & (xy[:, 0] < mask.shape[1]) & (xy[:, 1] >= 0) & (xy[:, 1] < mask.shape[0])
            coverage = float(np.mean(inside & (mask[np.clip(xy[:, 1], 0, mask.shape[0] - 1), np.clip(xy[:, 0], 0, mask.shape[1] - 1)] > 0)))
            if coverage < 0.8:
                return self._fail('tracked_patch_outside_hand_mask', mask_coverage=coverage)
        src, dst = (src[inlier], dst[inlier])
        if mask is not None and np.any(mask) and (len(dst) < 45):
            roi = self._roi(gray.shape, mask, center, self.radius * scale)
            for point in dst:
                cv2.circle(roi, tuple(np.rint(point).astype(int)), 4, 0, -1)
            extra = cv2.goodFeaturesToTrack(gray, maxCorners=80 - len(dst), qualityLevel=0.015, minDistance=3, mask=roi, blockSize=3)
            if extra is not None:
                new = extra.reshape(-1, 2)
                origin = (new - transform[:, 2]) @ np.linalg.inv(transform[:, :2]).T
                src = np.vstack((src, origin))
                dst = np.vstack((dst, new))
        self.reference_points = src.astype(np.float32).reshape(-1, 1, 2)
        self.points = dst.astype(np.float32).reshape(-1, 1, 2)
        self.previous = gray
        self.failed_frames = 0
        self.matrix = transform
        self.last = {'valid': True, 'reason': 'tracked', 'point_count': len(dst), 'center_xy': center.tolist(), 'radius_px': self.radius * scale, 'scale': scale, 'rotation_rad': rotation, 'reprojection_error_px': rms, 'mask_coverage': coverage, 'median_patch_correlation': float(np.median(correlations)), 'method': 'LK forward/backward + RANSAC on palm image points; no image warp'}
        return self.last
