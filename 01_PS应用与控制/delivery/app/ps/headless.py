"""Same segmentation and stateful recognition as the desktop, without overlays."""
import time
import numpy as np
import reference
from skin_detection import skin_mask, clean_mask, load_config
from background_subtraction import make_filter
from connected_regions import select_hand_region
from palm_geometry import analyze_palm
from finger_detection import detect_fingers
from gesture_classifier import GesturePipeline, open_hand_order, wrapped
from compat_records import replace
from palm_edges import PalmEdgeAssist

class HeadlessRecognizer:

    def __init__(self, config, automatic=False, edge_assist=False, lowtip_tracking=False):
        self.config = config
        self.automatic = automatic
        self.lowtip_tracking = bool(automatic and lowtip_tracking)
        self.edge_assist_enabled = bool(automatic and edge_assist)
        if automatic:
            from automatic import BlackBackground
            self.background = BlackBackground(config.detection_roi)
        else:
            self.background = make_filter(config)
        self.reset()

    def reset(self, reason='startup'):
        c = self.config
        self.calibration_candidate = None
        self.calibration_count = 0
        self.pipeline = GesturePipeline(c.gesture_confirm_frames, c.gesture_hold_frames, c.identity_memory_frames, reset_reason=reason)
        self.pipeline.motion_enabled = c.palm_motion_enabled
        self.pipeline.lowtip_tracking = self.lowtip_tracking
        self.pipeline.motion.recoverable = self.lowtip_tracking
        if self.edge_assist_enabled:
            self.pipeline.edge_assist = PalmEdgeAssist()
        if self.automatic:
            from automatic import OpenHandObserver
            self.open_observer = OpenHandObserver(c.calibration_stable_frames)

    def command(self, command):
        if command == 'B':
            self.background.start_capture()
        elif command == 'G':
            self.background.toggle()
        elif command == 'C':
            self.background.clear()
        elif command != 'K':
            raise ValueError('Expected B, G, C or K')
        self.reset('operator_' + command)

    def process(self, frame):
        c = self.config
        if frame.dtype != np.uint8 or frame.shape != (c.height, c.width, 3):
            raise ValueError('Require configured resolution uint8 BGR; no implicit resize')
        start = time.perf_counter()
        raw = skin_mask(frame, c)
        self.background.threshold, self.background.roi = (c.background_threshold, c.detection_roi)
        gated, foreground = self.background.apply(frame, raw)
        # Closing bridges narrow real finger gaps on the 320x240 silhouette.
        # Keep opening/hole limits but do not manufacture foreground in gaps.
        mask_config = replace(c, closing_iterations=0) if self.lowtip_tracking else c
        clean = clean_mask(gated, mask_config)
        segmented = time.perf_counter()
        final, candidate, components = select_hand_region(clean, c.min_area, c.component_max_area_fraction, c.component_ambiguity_ratio, c.detection_roi)
        selected_at = time.perf_counter()
        palm = analyze_palm(final, candidate, c.min_palm_radius)
        palm_at = time.perf_counter()
        if candidate is not None and c.detection_roi is not None:
            entry = next((e for e in components['components'] if e['label'] == candidate['component_label']))
            palm.info['touches_roi_border'] = entry['touches_roi_border']
            palm.info['active_roi_xywh'] = list(c.detection_roi)
            palm.info['touches_border'] |= entry['touches_roi_border']
        features = detect_fingers(palm, c.tip_min_radius_ratio, c.defect_min_depth_ratio,
                                  separate_close_tips=self.automatic)
        features_at = time.perf_counter()
        self.last_palm, self.last_features = palm, features
        pending = False
        stable_open = self.open_observer.update(palm, features) if self.automatic else False
        if self.pipeline.classifier.reference is not None:
            self.calibration_candidate = None
            self.calibration_count = 0
        if self.pipeline.classifier.reference is None and c.calibration_stable_frames > 1:
            order = open_hand_order(features.tips) if palm.valid and features.info['valid'] else None
            if order is None or features.info.get('valley_count', 0) < 3:
                self.calibration_count = 0
                self.calibration_candidate = None
            else:
                angles = np.asarray([features.tips[i]['angle_rad'] for i in order])
                ratios = np.asarray([features.tips[i]['radius_ratio'] for i in order])
                current = (angles, ratios, np.asarray(palm.center, float), palm.radius)
                old = self.calibration_candidate
                stable = old is not None and np.max(np.abs(wrapped(angles-old[0]))) < np.deg2rad(12)
                stable = stable and np.max(np.abs(ratios / old[1] - 1)) < 0.18
                stable = stable and np.linalg.norm(current[2]-old[2]) < 0.35 * palm.radius
                stable = stable and 0.85 < palm.radius / old[3] < 1.18
                self.calibration_count = self.calibration_count + 1 if stable else 1
                self.calibration_candidate = current
                pending = self.calibration_count < c.calibration_stable_frames
        classification_features = features
        if pending:
            info = dict(features.info, valid=False)
            classification_features = replace(features, info=info)
        result = self.pipeline.update(palm, classification_features, frame)
        if (self.automatic and stable_open and
                self.pipeline.classifier.reference is not None and
                (not result['raw'].get('reliable') or result['raw'].get('code') != '1111')):
            # An independently observed stable open hand is the only automatic
            # reset trigger. Never reset from a timer or guess bent-finger IDs.
            self.pipeline = GesturePipeline(c.gesture_confirm_frames, c.gesture_hold_frames,
                                            c.identity_memory_frames, reset_reason='automatic_stable_open_reacquire')
            self.pipeline.motion_enabled = c.palm_motion_enabled
            self.pipeline.lowtip_tracking = self.lowtip_tracking
            self.pipeline.motion.recoverable = self.lowtip_tracking
            if self.edge_assist_enabled:
                self.pipeline.edge_assist = PalmEdgeAssist()
            result = self.pipeline.update(palm, features, frame)
            result['automatic_reacquired'] = True
            pending = False
        if self.lowtip_tracking:
            self.last_features = getattr(self.pipeline, 'classification_features', features)
        if self.automatic:
            if result['raw'].get('reason') == 'hand_changed_press_K_and_show_open_hand':
                result['raw']['reason'] = 'hand_changed_hold_five_open_for_automatic_reacquire'
            result['automatic'] = {'stable_open_frames': self.open_observer.count,
                                   'required': self.open_observer.required,
                                   'reacquired': result.get('automatic_reacquired', False)}
        if pending:
            result['raw']['reason'] = 'hold_five_open_still_for_stable_calibration'
        result['lowtip_tracking'] = self.lowtip_tracking
        result['calibration_progress'] = dict(observed=self.calibration_count,
                                            required=c.calibration_stable_frames)
        # Each JSONL row already has a frame. Avoid re-serializing the last 45
        # decisions on every frame; the full sequence remains in frames.jsonl.
        if 'recent_decisions' in result:
            result['recent_decisions'] = result['recent_decisions'][-1:]
        end = time.perf_counter()
        masks = {'skin_mask': raw, 'foreground_mask': foreground, 'combined_mask': gated, 'clean_mask': clean, 'final_hand_mask': final}
        if self.pipeline.edge_assist is not None:
            masks.update(self.pipeline.edge_assist.last_images)
        return (result, masks, {'segmentation_ms': (segmented - start) * 1000, 'geometry_ms': (end - segmented) * 1000, 'components_ms': (selected_at-segmented)*1000, 'palm_ms': (palm_at-selected_at)*1000, 'fingertips_ms': (features_at-palm_at)*1000, 'identity_ms': (end-features_at)*1000, 'edge_assist_ms': self.pipeline.last_edge_ms, 'total_ms': (end - start) * 1000})
