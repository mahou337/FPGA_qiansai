"""Classical skin -> palm -> hull/defects -> tips -> conservative finger states."""
from compat_records import MISSING
from compat_cv import find_contours
import argparse
from compat_records import asdict, dataclass, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid
try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise SystemExit('Missing dependency: {0}; use an existing Python with OpenCV and NumPy.'.format(exc)) from exc
from palm_geometry import analyze_palm, distance_view
from finger_detection import detect_fingers, draw_finger_detection
from gesture_classifier import GesturePipeline, unknown
from background_subtraction import make_filter
from connected_regions import select_hand_region
PROJECT_DIR = Path(__file__).resolve().parent
WINDOW_IMAGES = (('Original', 'original'), ('Skin Mask', 'skin_mask'), ('Foreground Mask', 'foreground_mask'), ('Combined Mask', 'combined_mask'), ('Clean Mask', 'clean_mask'), ('Hand Region', 'hand_region'), ('Finger Detection', 'finger_detection'))
WINDOWS = tuple((name for name, _ in WINDOW_IMAGES))
SLIDERS = (('Cr Min', 'cr_min'), ('Cr Max', 'cr_max'), ('Cb Min', 'cb_min'), ('Cb Max', 'cb_max'))

@dataclass
class Config:
    _field_specs = [('camera_index', 0), ('camera_backend', 'auto'), ('width', 320), ('height', 240), ('cr_min', 133), ('cr_max', 173), ('cb_min', 77), ('cb_max', 127), ('kernel_size', 3), ('opening_iterations', 1), ('closing_iterations', 1), ('min_area', 500), ('record_interval_seconds', 1.0), ('results_dir', 'results'), ('min_palm_radius', 3), ('tip_min_radius_ratio', 1.45), ('defect_min_depth_ratio', 0.3), ('gesture_confirm_frames', 1), ('gesture_hold_frames', 0), ('identity_memory_frames', 45), ('show_contour', True), ('show_hull', True), ('show_defects', True), ('show_tips', True), ('background_enabled', False), ('background_frames', 20), ('background_threshold', 25), ('detection_roi', None), ('component_max_area_fraction', 0.8), ('component_ambiguity_ratio', 0.65), ('palm_motion_enabled', True), ('small_hole_max_area', 0), ('calibration_stable_frames', 1)]

    def validate(self):
        for name in ('camera_index', 'width', 'height', 'cr_min', 'cr_max', 'cb_min', 'cb_max', 'kernel_size', 'opening_iterations', 'closing_iterations', 'min_area', 'min_palm_radius', 'gesture_confirm_frames', 'gesture_hold_frames', 'identity_memory_frames'):
            if type(getattr(self, name)) is not int:
                raise ValueError('{0} must be an integer'.format(name))
        if type(self.small_hole_max_area) is not int or not 0 <= self.small_hole_max_area <= 128:
            raise ValueError('small_hole_max_area must be an integer in [0,128]')
        if type(self.calibration_stable_frames) is not int or not 1 <= self.calibration_stable_frames <= 10:
            raise ValueError('calibration_stable_frames must be an integer in [1,10]')
        if self.camera_index < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError('Invalid camera index or resolution')
        for channel in ('cr', 'cb'):
            if not 0 <= getattr(self, channel + '_min') <= getattr(self, channel + '_max') <= 255:
                raise ValueError('{0}: require 0 <= min <= max <= 255'.format(channel))
        if not 1 <= self.kernel_size <= 31 or self.kernel_size % 2 == 0:
            raise ValueError('kernel_size must be odd and in [1,31]')
        if not 0 <= self.opening_iterations <= 10 or not 0 <= self.closing_iterations <= 10:
            raise ValueError('Morphology iterations must be in [0,10]')
        for name in ('min_area', 'min_palm_radius', 'identity_memory_frames'):
            if getattr(self, name) < 1:
                raise ValueError('{0} must be >= 1'.format(name))
        if not 1 <= self.gesture_confirm_frames <= 30 or not 0 <= self.gesture_hold_frames <= 60:
            raise ValueError('Invalid gesture debounce interval')
        for name, lo, hi in (('record_interval_seconds', 0.05, 3600), ('tip_min_radius_ratio', 1.1, 4), ('defect_min_depth_ratio', 0.05, 2)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (not np.isfinite(value)) or (not lo <= value <= hi):
                raise ValueError('{0} must be finite and in [{1},{2}]'.format(name, lo, hi))
        for name in ('show_contour', 'show_hull', 'show_defects', 'show_tips', 'palm_motion_enabled'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('{0} must be boolean'.format(name))
        if self.camera_backend not in ('auto', 'dshow', 'msmf', 'any'):
            raise ValueError('camera_backend must be auto/dshow/msmf/any')
        if not isinstance(self.results_dir, str) or not self.results_dir.strip():
            raise ValueError('results_dir must be a nonempty path')
        if type(self.background_enabled) is not bool:
            raise ValueError('background_enabled must be boolean')
        if type(self.background_frames) is not int or not 3 <= self.background_frames <= 120:
            raise ValueError('background_frames must be in [3,120]')
        if type(self.background_threshold) is not int or not 0 <= self.background_threshold <= 100:
            raise ValueError('background_threshold must be in [0,100]')
        for name in ('component_max_area_fraction', 'component_ambiguity_ratio'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (not np.isfinite(value)) or (not 0 < value <= 1):
                raise ValueError('{0} must be finite and in (0,1]'.format(name))
        if self.detection_roi is not None:
            roi = self.detection_roi
            if not isinstance(roi, (list, tuple)) or len(roi) != 4 or any((type(v) is not int for v in roi)):
                raise ValueError('detection_roi must be [x,y,width,height] or null')
            if roi[0] < 0 or roi[1] < 0 or roi[2] < 1 or (roi[3] < 1):
                raise ValueError('detection_roi requires nonnegative x,y and positive width,height')

def load_config(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError('Config must be a JSON object')
    unknown = set(data) - {field.name for field in fields(Config)}
    if unknown:
        raise ValueError('Unknown configuration keys: {0}'.format(sorted(unknown)))
    config = Config(**data)
    config.validate()
    return config

def skin_mask(bgr, config):
    """Inclusive Cr/Cb comparisons; OpenCV channel order is Y, Cr, Cb."""
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    return cv2.inRange(ycrcb, (0, config.cr_min, config.cb_min), (255, config.cr_max, config.cb_max))

def erode_mask(mask, kernel, iterations=1):
    return cv2.erode(mask, kernel, iterations=iterations, borderType=cv2.BORDER_REPLICATE)

def dilate_mask(mask, kernel, iterations=1):
    return cv2.dilate(mask, kernel, iterations=iterations, borderType=cv2.BORDER_REPLICATE)

def clean_mask(mask, config):
    """Opening then closing. No extra dilation or implicit smoothing.

    N opening iterations = N erosions followed by N dilations (likewise
    for closing), matching OpenCV morphologyEx iteration semantics.
    Replicated edge pixels make the image-border convention explicit.
    """
    kernel = np.ones((config.kernel_size, config.kernel_size), dtype=np.uint8)
    clean = mask.copy()
    if config.opening_iterations:
        n = config.opening_iterations
        clean = dilate_mask(erode_mask(clean, kernel, n), kernel, n)
    if config.closing_iterations:
        n = config.closing_iterations
        clean = erode_mask(dilate_mask(clean, kernel, n), kernel, n)
    if config.small_hole_max_area:
        clean = fill_small_internal_holes(clean, config.small_hole_max_area)
    return clean

def fill_small_internal_holes(mask, max_area, max_fraction=0.04):
    """Repair only small enclosed gaps; never close finger valleys or borders.

    Reject the entire repair when its total exceeds 4% of foreground. Large
    missing regions remain unknown instead of synthesizing a hand silhouette.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        cv2.bitwise_not(mask), connectivity=8)
    h, w = mask.shape
    selected = np.zeros(count, np.uint8)
    total = 0
    for label in range(1, count):
        x, y, bw, bh, area = map(int, stats[label])
        if 0 < area <= max_area and x > 0 and y > 0 and x + bw < w and y + bh < h:
            selected[label] = 255
            total += area
    if not total or total > max_fraction * np.count_nonzero(mask):
        return mask
    return cv2.bitwise_or(mask, selected[labels])

def largest_candidate(mask, min_area):
    """Return largest external contour passing the contour-area threshold.

    Area is polygon area in pixel^2, not foreground pixel count. Face, arm
    and skin-colored objects can win this selection as easily as a hand.
    """
    contours, _ = find_contours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < min_area:
        return None
    return {'contour': contour, 'area': area, 'bbox': tuple((int(v) for v in cv2.boundingRect(contour)))}

def draw_region(bgr, candidate, components=None):
    view = bgr.copy()
    if candidate is None:
        label, color = (components['status'] if components else 'No Hand Region', (0, 0, 255))
    else:
        x, y, w, h = candidate['bbox']
        color = (0, 255, 0)
        cv2.drawContours(view, [candidate['contour']], -1, color, 1)
        cv2.rectangle(view, (x, y), (x + w - 1, y + h - 1), color, 1)
        label = 'Skin candidate: {0:.0f} px'.format(candidate.get('component_pixel_area', candidate['area']))
    cv2.putText(view, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(view, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if components:
        label = '8-CC: {0} | eligible: {1}'.format(components['component_count'], components['eligible_count'])
        cv2.putText(view, label, (6, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(view, label, (6, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 0), 1, cv2.LINE_AA)
    return view

def open_camera(config):
    options = {'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF, 'any': cv2.CAP_ANY}
    names = ['dshow', 'msmf', 'any'] if sys.platform == 'win32' else ['any']
    if config.camera_backend != 'auto':
        names = [config.camera_backend]
    attempts = []
    for name in names:
        cap = cv2.VideoCapture()
        keep = False
        try:
            if not cap.open(config.camera_index, options[name]):
                attempts.append('{0}: could not open'.format(name))
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
            for _ in range(10):
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    backend = cap.getBackendName()
                    keep = True
                    return (cap, frame, backend)
            attempts.append('{0}: opened but returned no frames'.format(name))
        except cv2.error as exc:
            attempts.append('{0}: {1}'.format(name, exc))
        finally:
            if not keep:
                cap.release()
    raise RuntimeError('Cannot open camera {0} or read frames. Check connection, Windows camera privacy permissions, and whether another application is using it. Try --camera 1 or --backend msmf. Attempts: '.format(config.camera_index) + '; '.join(attempts))

def read_sliders(config):
    values = {attr: cv2.getTrackbarPos(title, 'Skin Mask') for title, attr in SLIDERS}
    for channel in ('cr', 'cb'):
        low, high = (channel + '_min', channel + '_max')
        if values[low] > values[high]:
            values[high] = values[low]
            cv2.setTrackbarPos(channel.title() + ' Max', 'Skin Mask', values[high])
    for attr, value in values.items():
        setattr(config, attr, value)
    config.background_threshold = cv2.getTrackbarPos('BG Threshold', 'Foreground Mask')

class FrameImages(dict):
    """Only image arrays are dict entries; metadata also survives no-candidate frames."""
    segmentation = None
    components = None
    processing = None

def process_mask(bgr, raw, clean, config, pipeline=None):
    """Reuse supplied masks, preserving source coordinates throughout."""
    started = time.perf_counter()
    final, candidate, components = select_hand_region(clean, config.min_area, config.component_max_area_fraction, config.component_ambiguity_ratio, config.detection_roi)
    selected_at = time.perf_counter()
    palm = analyze_palm(final, candidate, config.min_palm_radius)
    if candidate is not None and config.detection_roi is not None:
        selected_entry = next((e for e in components['components'] if e['label'] == candidate['component_label']))
        palm.info['touches_roi_border'] = selected_entry['touches_roi_border']
        palm.info['active_roi_xywh'] = list(config.detection_roi)
        palm.info['touches_border'] = palm.info['touches_border'] or selected_entry['touches_roi_border']
    features = detect_fingers(palm, config.tip_min_radius_ratio, config.defect_min_depth_ratio)
    pipeline = pipeline or GesturePipeline(config.gesture_confirm_frames, config.gesture_hold_frames, config.identity_memory_frames)
    pipeline.motion_enabled = config.palm_motion_enabled
    gesture = pipeline.update(palm, features, bgr)
    view = draw_region(bgr, candidate, components)
    if palm.center is not None:
        cv2.circle(view, palm.center, max(1, int(round(palm.radius))), (255, 255, 255), 1)
        cv2.drawMarker(view, palm.center, (255, 255, 255), cv2.MARKER_CROSS, 10, 1)
    if candidate is not None:
        candidate.update(palm=palm.info, features=features.to_dict(), gesture=gesture, components=components)
    images = FrameImages({'original': bgr.copy(), 'skin_mask': raw, 'clean_mask': clean, 'hand_region': view, 'hand_mask': palm.mask, 'palm_distance': distance_view(palm), 'final_hand_mask': final, 'finger_detection': draw_finger_detection(bgr, palm, features, gesture, config)})
    images.components = components
    images.processing = {'components_ms': (selected_at - started) * 1000, 'geometry_and_overlay_ms': (time.perf_counter() - selected_at) * 1000}
    return (images, candidate)

def process_frame(bgr, config, pipeline=None, background=None):
    started = time.perf_counter()
    raw = skin_mask(bgr, config)
    skin_at = time.perf_counter()
    if background is None:
        background = make_filter(config)
    background.threshold = config.background_threshold
    background.roi = config.detection_roi
    gated, foreground = background.apply(bgr, raw)
    background_at = time.perf_counter()
    clean = clean_mask(gated, config)
    morphology_at = time.perf_counter()
    images, candidate = process_mask(bgr, raw, clean, config, pipeline)
    images['foreground_mask'] = foreground
    images['gated_mask'] = gated
    images['combined_mask'] = gated
    if background.reference is not None:
        images['background_reference'] = background.reference.copy()
    if candidate is not None:
        candidate['segmentation'] = dict(background.last_info)
    images.segmentation = dict(background.last_info)
    background.annotate(images['hand_region'])
    images.processing.update(skin_ms=(skin_at - started) * 1000, background_ms=(background_at - skin_at) * 1000, morphology_ms=(morphology_at - background_at) * 1000, total_ms=(time.perf_counter() - started) * 1000)
    images.processing['foreground_pixels'] = {name: int(np.count_nonzero(images[name])) for name in ('skin_mask', 'foreground_mask', 'combined_mask', 'clean_mask', 'final_hand_mask')}
    images.processing['total_ms'] = (time.perf_counter() - started) * 1000
    return (images, candidate)

def save_snapshot(images, config, candidate, backend, source='camera', segmentation=None):
    root = Path(config.results_dir)
    if not root.is_absolute():
        root = PROJECT_DIR / root
    root.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).astimezone()
    while True:
        folder = root / (captured_at.strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8])
        try:
            folder.mkdir(exist_ok=False)
            break
        except FileExistsError:
            continue
    h, w = images['original'].shape[:2]
    absent = {'raw': unknown('no_region'), 'states': dict.fromkeys(('Thumb', 'Index', 'Middle', 'Ring'), '?'), 'code': '????', 'status': 'NO HAND', 'reliable': False, 'command_ready': False}
    if getattr(images, 'components', None) and images.components['ambiguous']:
        absent['raw'] = unknown('ambiguous_skin_regions')
        absent['status'] = 'AMBIGUOUS'
    metadata = {'schema_version': 4, 'captured_at': captured_at.isoformat(), 'source': source, 'camera_backend_actual': backend, 'resolution_actual': {'width': w, 'height': h}, 'config': asdict(config), 'color_conversion': 'cv2.COLOR_BGR2YCrCb', 'channel_order': ['Y', 'Cr', 'Cb'], 'threshold_bounds': 'inclusive; Y unrestricted', 'morphology': {'order': ['opening', 'closing'], 'border': 'replicate', 'kernel_shape': 'rectangle'}, 'candidate': None if candidate is None else {'contour_area_px2': candidate['area'], 'bounding_rect_xywh': list(candidate['bbox']), 'pixel_area': candidate.get('component_pixel_area'), 'centroid_xy': candidate.get('centroid_xy'), 'is_confirmed_hand': False}, 'palm': None if candidate is None else candidate['palm'], 'features': None if candidate is None else candidate['features'], 'segmentation': segmentation if segmentation is not None else getattr(images, 'segmentation', None), 'components': getattr(images, 'components', None), 'processing': getattr(images, 'processing', None), 'gesture': absent if candidate is None else candidate['gesture'], 'versions': {'python': sys.version.split()[0], 'opencv': cv2.__version__, 'numpy': np.__version__}, 'files': {name: name + '.png' for name in images}}
    try:
        for name, pixels in images.items():
            ok, encoded = cv2.imencode('.png', pixels)
            if not ok:
                raise OSError('PNG encoding failed: {0}'.format(name))
            with (folder / (name + '.png')).open('xb') as stream:
                stream.write(encoded.tobytes())
        with (folder / 'metadata.json').open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except Exception as exc:
        raise OSError('Snapshot incomplete at {0}: {1}'.format(folder, exc)) from exc
    return folder

def create_windows(config):
    positions = ((10, 30), (350, 30), (690, 30), (1030, 30), (10, 400), (350, 530), (690, 430))
    for name, position in zip(WINDOWS, positions):
        cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
        cv2.moveWindow(name, *position)
    for title, attr in SLIDERS:
        cv2.createTrackbar(title, 'Skin Mask', getattr(config, attr), 255, lambda _: None)
    cv2.createTrackbar('BG Threshold', 'Foreground Mask', config.background_threshold, 100, lambda _: None)

def handle_background_key(key, background, config):
    if key in (ord('b'), ord('B')):
        background.start_capture()
        print('Capturing EMPTY raw background: keep hand OUT until calibrated.', flush=True)
    elif key in (ord('g'), ord('G')):
        print('Background subtraction {0}'.format('ON' if background.toggle() else 'OFF'), flush=True)
    elif key in (ord('c'), ord('C')):
        background.clear()
        print('Background not calibrated; using skin-only fallback.', flush=True)
    else:
        return False
    return True

def show_images(images, candidate=None):
    for name, key in WINDOW_IMAGES:
        cv2.imshow(name, images[key])

def run(config, probe_camera=False, max_frames=0, save_on_start=False):
    cap = None
    gui_created = False
    pipeline = GesturePipeline(config.gesture_confirm_frames, config.gesture_hold_frames, config.identity_memory_frames)
    background = make_filter(config)
    try:
        cap, frame, backend = open_camera(config)
        h, w = frame.shape[:2]
        print('Camera {0}: {1}; requested {2}x{3}; actual {4}x{5}'.format(config.camera_index, backend, config.width, config.height, w, h), flush=True)
        if not probe_camera:
            gui_created = True
            create_windows(config)
            print('Q quit | S save | R timed save | B capture EMPTY background | G toggle | C clear | K reset finger calibration.', flush=True)
            print('Skin Mask = raw color threshold; Clean Mask = background/ROI gate + morphology. Show all five fingers after calibration.', flush=True)
            print('Candidate skin is not necessarily a hand; UNKNOWN/HOLD never authorizes a new command.', flush=True)
        limit = max_frames or 10 if probe_camera else max_frames
        recording, next_save, count, read_failures = (False, 0.0, 0, 0)
        previous = None
        while True:
            if not probe_camera:
                read_sliders(config)
            images, candidate = process_frame(frame, config, pipeline, background)
            count += 1
            if candidate is not None:
                result = candidate['gesture']
                summary = (result['code'], result['raw']['code'], result['status'], result['raw']['reason'])
            else:
                summary = ('????', '????', 'NO HAND', 'no_region')
            if summary != previous:
                print('Gesture={0} Raw={1} {2} ({3})'.format(summary[0], summary[1], summary[2], summary[3]), flush=True)
                previous = summary
            key = -1
            if not probe_camera:
                show_images(images, candidate)
                key = cv2.waitKey(1) & 255
            if key in (ord('q'), ord('Q'), 27):
                break
            if handle_background_key(key, background, config) or key in (ord('k'), ord('K')):
                pipeline = GesturePipeline(config.gesture_confirm_frames, config.gesture_hold_frames, config.identity_memory_frames, reset_reason='keyboard_' + chr(key).upper())
                if key in (ord('k'), ord('K')):
                    print('Finger calibration cleared: open ALL FIVE fingers clearly.', flush=True)
            if key in (ord('r'), ord('R')):
                recording = not recording
                next_save = 0.0
                print('Recording {0}'.format('ON' if recording else 'OFF'), flush=True)
            now = time.monotonic()
            if key in (ord('s'), ord('S')) or (save_on_start and count == 1) or (recording and now >= next_save):
                try:
                    print('Saved: {0}'.format(save_snapshot(images, config, candidate, backend)), flush=True)
                except (OSError, cv2.error) as exc:
                    print('Save failed: {0}'.format(exc), file=sys.stderr)
                    recording = False
                next_save = now + config.record_interval_seconds
            if limit and count >= limit:
                break
            if not probe_camera and any((cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1 for name in WINDOWS)):
                break
            while True:
                ok, next_frame = cap.read()
                if ok and next_frame is not None and next_frame.size:
                    frame = next_frame
                    read_failures = 0
                    break
                read_failures += 1
                if read_failures >= 10:
                    raise RuntimeError('Camera stopped returning frames (10 consecutive failures).')
                if not probe_camera and cv2.waitKey(30) & 255 in (ord('q'), ord('Q'), 27):
                    return 0
        print('Processed {0} frames.'.format(count), flush=True)
        return 0
    finally:
        if cap is not None:
            cap.release()
        if gui_created:
            cv2.destroyAllWindows()

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=PROJECT_DIR / 'config.json')
    parser.add_argument('--camera', type=int)
    parser.add_argument('--backend', choices=('auto', 'dshow', 'msmf', 'any'))
    for name in ('width', 'height', 'kernel-size', 'opening-iterations', 'closing-iterations', 'min-area'):
        parser.add_argument('--' + name, type=int)
    parser.add_argument('--results-dir')
    parser.add_argument('--probe-camera', action='store_true')
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--save-on-start', action='store_true')
    parser.add_argument('--background', action='store_true', help='Enable background subtraction; skin-only fallback until B calibration')
    parser.add_argument('--background-threshold', type=int, help='Max BGR difference threshold [0,100], default 25')
    parser.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'), help='Optional fixed detection rectangle in actual image pixels')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        for name in ('camera', 'backend', 'width', 'height', 'kernel_size', 'opening_iterations', 'closing_iterations', 'min_area', 'results_dir'):
            value = getattr(args, name)
            if value is not None:
                setattr(config, {'camera': 'camera_index', 'backend': 'camera_backend'}.get(name, name), value)
        config.validate()
        if args.background:
            config.background_enabled = True
        if args.background_threshold is not None:
            config.background_threshold = args.background_threshold
        if args.roi is not None:
            config.detection_roi = args.roi
        config.validate()
        if args.max_frames < 0:
            raise ValueError('max-frames must be >= 0')
        return run(config, args.probe_camera, args.max_frames, args.save_on_start)
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        print('ERROR: {0}'.format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Stopped by user.')
        return 0
if __name__ == '__main__':
    raise SystemExit(main())
