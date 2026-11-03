"""Stage-1 real camera acceptance runner. Python 3.5+, no simulated capture mode."""
from __future__ import print_function
import argparse
import errno
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import time
import uuid


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), value)


def check_storage(mount, mountinfo='/proc/self/mountinfo'):
    root = os.path.realpath(str(mount))
    found = None
    with open(mountinfo) as stream:
        for line in stream:
            left, right = line.rstrip().split(' - ', 1)
            fields, info = left.split(), right.split()
            if unescape_mount(fields[4]) == root:
                found = (fields, info)
                break
    if found is None:
        raise RuntimeError('Output must be an actual mounted SD FAT filesystem: ' + root)
    fields, info = found
    source = os.path.realpath(unescape_mount(info[1]))
    if info[0] not in ('vfat', 'msdos') or source != '/dev/mmcblk0p1':
        raise RuntimeError('Expected SD0 FAT partition /dev/mmcblk0p1, got {0} {1}'.format(source, info[0]))
    if 'rw' not in fields[5].split(','):
        raise RuntimeError('SD output filesystem is read-only')
    device = os.stat(source)
    if not stat.S_ISBLK(device.st_mode):
        raise RuntimeError('Mount source is not a block device')
    if os.stat(root).st_dev != device.st_rdev:
        raise RuntimeError('Mount source/device identity mismatch')
    free = os.statvfs(root)
    available = free.f_bavail * free.f_frsize
    if available < 32 * 1024 * 1024:
        raise RuntimeError('At least 32 MiB free space required on SD FAT')
    return {'mount': root, 'source': source, 'filesystem': info[0], 'available_bytes': available,
            'mountinfo': fields + ['-'] + info}


class RunLog(object):
    def __init__(self, directory):
        self.directory = Path(directory)
        self.stream = open(str(self.directory / 'test.log'), 'x', buffering=1)
        self.started = time.monotonic()
        self.records = []

    def event(self, name, **values):
        row = {'event': name, 'elapsed_ms': round((time.monotonic()-self.started)*1000, 3)}
        row.update(values)
        text = '[TEST] ' + name + ' ' + json.dumps(row, ensure_ascii=True, sort_keys=True)
        print(text, flush=True)
        self.stream.write(text+'\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.records.append(row)

    def summary(self, value):
        path = self.directory / 'summary.json'
        with open(str(path), 'x') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

    def close(self):
        self.stream.close()


def validate_diag(diag, seq):
    if (diag.get('abi_version') != 1 or diag.get('result') != 0 or diag.get('broken') or
            diag.get('sequence') != seq or diag.get('capture_status', 0) & 7 != 1 or
            diag.get('words') != 153600 or diag.get('frame_bytes') != 614400 or
            diag.get('dma_length') != 614400 or diag.get('dma_status', 0) & 0x70 or
            diag.get('dma_status', 0) & 0x1002 != 0x1002):
        raise RuntimeError('Invalid driver completion: ' + json.dumps(diag, sort_keys=True))


def save_image(path, image, cv2, np):
    if image.shape != (480, 640, 3) or image.dtype != np.uint8:
        raise RuntimeError('Capture is not a 640x480 uint8 BGR frame')
    if path.exists():
        raise RuntimeError('Refusing to overwrite image')
    if not cv2.imwrite(str(path), image):
        raise IOError('OpenCV image encoder failed: ' + str(path))
    with open(str(path), 'rb') as stream:
        os.fsync(stream.fileno())
    decoded = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if decoded is None or not np.array_equal(decoded, image):
        raise IOError('Saved PNG did not pass lossless readback')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mount', default='/mnt/sdcard', help='Mounted SD0 FAT partition (not a directory on rootfs)')
    parser.add_argument('--device', default='/dev/gesture-camera')
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=3.0)
    parser.add_argument('--settle', type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.frames < 3 or args.frames > 100 or not 0 < args.timeout <= 10 or not 0.2 <= args.settle <= 30:
        parser.error('frames: 3..100; timeout: (0,10]; settle: [0.2,30] seconds')
    log = None; hw = None; rc = 1; frames = []; stage = 'preflight'; mode_value = None
    started = time.monotonic()
    print('[TEST] BEGIN', flush=True)
    try:
        if os.geteuid() != 0:
            raise PermissionError('Run as root to access the exclusive driver')
        storage = check_storage(args.mount)
        parent = Path(storage['mount']) / 'camera-tests'
        parent.mkdir(exist_ok=True)
        if parent.is_symlink() or os.path.realpath(str(parent)) != str(parent):
            raise RuntimeError('Refusing symlinked output directory')
        directory = parent / ('run-' + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        log = RunLog(directory)
        log.event('STORAGE', **storage)
        log.event('RUNTIME', python=sys.version, kernel=platform.release(), directory=str(directory))
        expected_file = Path(__file__).resolve().parents[1] / 'EXPECTED_KERNEL_RELEASE'
        if not expected_file.is_file() or platform.release() != expected_file.read_text().strip():
            raise RuntimeError('Kernel release does not match this delivery')
        if not stat.S_ISCHR(os.stat(args.device).st_mode):
            raise RuntimeError('Camera device is not a character device')
        driver = os.path.realpath('/sys/class/misc/gesture-camera/device/driver')
        if os.path.basename(driver) != 'gesture-vga':
            raise RuntimeError('Device is not bound to gesture-vga: ' + driver)
        import cv2
        import numpy as np
        from hardware_vga import HardwareVGA
        log.event('DEPENDENCIES', opencv=cv2.__version__, numpy=np.__version__)
        for command in (['dmesg'],):
            try:
                import subprocess
                with open(str(directory / 'dmesg-before.txt'), 'xb') as stream:
                    subprocess.check_call(command, stdout=stream, stderr=subprocess.STDOUT)
                    stream.flush(); os.fsync(stream.fileno())
            except Exception as exc:
                log.event('EVIDENCE_WARNING', message=str(exc))
        tree = Path('/sys/firmware/fdt')
        if tree.is_file():
            with open(str(directory / 'running.dtb'), 'xb') as stream:
                stream.write(tree.read_bytes()); stream.flush(); os.fsync(stream.fileno())
        stage = 'GST2'; hw = HardwareVGA(args.device)
        log.event('GST2_ID', value='0x{0:08X}'.format(hw.read(0)), dimensions='640x480')
        hw.report_sensor_id = lambda chip: log.event('OV5640_ID', value='0x{0:04X}'.format(chip))
        stage = 'initialize'
        hw.initialize(Path(__file__).resolve().parents[1] / 'config' / 'ov5640_vga_rgb565.json')
        registers = (0x3034,0x3035,0x3036,0x3037,0x3108,0x460c,0x3824,
                     0x3808,0x3809,0x380a,0x380b,0x4300,0x501f,0x4740)
        log.event('INITIALIZED', registers={'0x{0:04X}'.format(a): hw.camera_read(a) for a in registers})
        mode_value = hw.camera_read(0x503d)
        previous_seq = None
        for mode in ('colorbar', 'real'):
            stage = mode
            wanted = mode_value | 0x80 if mode == 'colorbar' else mode_value & 0x7f
            hw.camera_write(0x503d, wanted)
            actual = hw.camera_read(0x503d)
            if actual != wanted:
                raise RuntimeError('0x503D readback mismatch: {0:02X} != {1:02X}'.format(actual,wanted))
            log.event('MODE', mode=mode, register_503d=actual, settle_seconds=args.settle)
            time.sleep(args.settle)
            for index in range(args.frames):
                begin = time.monotonic()
                seq, image = hw.capture(args.timeout)
                diag = hw.diagnostics()
                validate_diag(diag, seq)
                if previous_seq is not None and seq != (previous_seq + 1) & 0xffffffff:
                    raise RuntimeError('Capture sequence skipped or repeated')
                previous_seq = seq
                path = directory / ('{0}-{1:02d}.png'.format(mode, index+1))
                save_image(path,image,cv2,np)
                row = {'mode': mode, 'index': index+1, 'sequence': seq, 'bytes': 614400,
                       'path': str(path), 'elapsed_ms': round((time.monotonic()-begin)*1000,3),
                       'return_code': 0, 'driver': diag}
                frames.append(row)
                log.event('COLORBAR_SAVED' if mode == 'colorbar' else 'FRAME_SAVED', **row)
        rc = 0
    except Exception as exc:
        message = '{0}: {1}'.format(type(exc).__name__, exc)
        details = {'stage': stage, 'return_code': 1, 'error': message}
        if hw is not None:
            try: details['driver'] = hw.diagnostics()
            except Exception as diag_error: details['diagnostics_error'] = str(diag_error)
        if log is not None: log.event('CAPTURE_FAIL', **details)
        else: print('[TEST] CAPTURE_FAIL '+json.dumps(details,sort_keys=True), file=sys.stderr, flush=True)
    finally:
        if hw is not None:
            try:
                if mode_value is not None and not hw.read(12) & 2:
                    hw.camera_write(0x503d, mode_value & 0x7f)
            except Exception as exc:
                rc = 1
                if log is not None: log.event('CLEANUP_FAIL', error=str(exc), return_code=1)
            finally:
                try: hw.close()
                except Exception as exc:
                    rc = 1
                    if log is not None: log.event('CLOSE_FAIL', error=str(exc))
        if log is not None:
            summary = {'return_code':rc, 'capture_transport_pass':rc==0,
                       'image_content_acceptance':'PENDING_HUMAN_REVIEW',
                       'hardware_capture_executed':bool(frames), 'full_board_acceptance':'PENDING_HUMAN_REVIEW',
                       'frames':frames, 'elapsed_seconds':time.monotonic()-started}
            try:
                log.summary(summary)
                os.sync()
                if rc == 0: log.event('CAPTURE_PASS', return_code=0, frames=len(frames), image_review='PENDING')
                log.event('END', return_code=rc, directory=str(log.directory), shutdown='Run poweroff, wait for shutdown, then remove power/card')
            finally:
                log.close()
        # Flush image data, metadata, logs and FAT directory entries. Never power off automatically.
        os.sync()
    return rc

if __name__ == '__main__':
    sys.exit(main())
