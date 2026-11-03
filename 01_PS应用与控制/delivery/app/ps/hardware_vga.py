"""Full VGA capture through the kernel-owned coherent DMA buffer (Linux only)."""
from array import array
import math
import os
import cv2
import numpy as np
from hardware import Hardware

# asm-generic ioctl encoding used by the ARMv7 board ABI; payload is fixed u32.
REG_READ = 0xC0084700
REG_WRITE = 0x40084701
CAPTURE = 0x40044702
GET_STATUS = 0x80304703
WIDTH, HEIGHT = 640, 480
FRAME_BYTES = WIDTH * HEIGHT * 2


def decode_frame(payload):
    if len(payload) != FRAME_BYTES:
        raise ValueError('Expected {0} RGB565 bytes, got {1}'.format(FRAME_BYTES, len(payload)))
    return cv2.cvtColor(np.frombuffer(payload, np.uint8).reshape(HEIGHT, WIDTH, 2),
                        cv2.COLOR_BGR5652BGR)


def recognition_frame(image):
    """Keep the original algorithm's pixel thresholds on an explicit QVGA input."""
    if image.shape != (HEIGHT, WIDTH, 3):
        raise ValueError('Hardware input must be a full 640x480 BGR frame')
    return cv2.resize(image, (320, 240), interpolation=cv2.INTER_AREA)


class HardwareVGA(Hardware):
    def __init__(self, device='/dev/gesture-camera'):
        import fcntl
        self._ioctl = fcntl.ioctl
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        try:
            if self.read(0) != 0x47535432:
                raise RuntimeError('Wrong PL image: VGA DMA requires GST2')
            if self.read(0x18) != (HEIGHT << 16) | WIDTH:
                raise RuntimeError('Expected 640x480 capture dimensions')
            self.control = self.read(4) & 15
        except Exception:
            self.close()
            raise

    def read(self, offset):
        pair = array('I', [offset, 0])
        self._ioctl(self.fd, REG_READ, pair, True)
        return pair[1]

    def write(self, offset, value):
        self._ioctl(self.fd, REG_WRITE, array('I', [offset, value]), True)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def initialize(self, table):
        # SCCB transactions and reset sequencing are shared with the QVGA backend.
        import json
        from pathlib import Path
        cfg = json.loads(Path(table).read_text())
        if (cfg.get('width'), cfg.get('height')) != (WIDTH, HEIGHT):
            raise ValueError('VGA hardware requires a VGA sensor register table')
        super().initialize(table)

    def diagnostics(self):
        values = array('I', [0] * 12)
        self._ioctl(self.fd, GET_STATUS, values, True)
        names = ('abi_version', 'capture_status', 'sequence', 'words',
                 'dma_status', 'dma_length', 'elapsed_us', 'result',
                 'frame_bytes', 'broken', 'dma_control', 'reserved')
        result = dict(zip(names, values))
        if result['result'] & 0x80000000:
            result['result'] -= 0x100000000
        return result

    def capture(self, timeout=1.0):
        if not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError('Capture timeout must be in (0, 10] seconds')
        self._ioctl(self.fd, CAPTURE, array('I', [max(1, math.ceil(timeout * 1000))]), True)
        payload = bytearray()
        while len(payload) < FRAME_BYTES:
            part = os.read(self.fd, FRAME_BYTES - len(payload))
            if not part:
                raise OSError('Short DMA frame returned by driver')
            payload.extend(part)
        return self.read(16), decode_frame(payload)
