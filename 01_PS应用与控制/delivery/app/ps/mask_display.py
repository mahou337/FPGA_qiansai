"""Python 3.5 / NumPy 1.14 compatible, independent of PNG diagnostics.
submit() snapshots bytes at <=5Hz, never performs device IO or waits on a lock.
Only the daemon worker owns the device fd. A single pending slot replaces old data.
"""
import collections
import errno
import os
import struct
import threading
import time

STATUS_IOCTL = 0x80204d00
MODE_IOCTL = 0x40044d01

def percentile(values, q):
    data = sorted(values)
    if not data:
        return None
    return data[int((len(data)-1)*q)]

class DeviceBackend(object):
    def __init__(self, path):
        import fcntl
        self.fcntl = fcntl
        self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = self.status()
            if info[0] != 0x4d534b31 or info[2] != 0x00f00140 or info[3] != 76800:
                raise RuntimeError('MSK1 identity/geometry mismatch')
        except Exception:
            os.close(self.fd)
            raise
    def status(self):
        raw = self.fcntl.ioctl(self.fd, STATUS_IOCTL, bytes(32))
        return struct.unpack('<8I', raw)
    def write(self, snapshot):
        count = os.write(self.fd, snapshot)
        if count != 76800:
            raise IOError('short mask write')
    def mode(self, value):
        self.fcntl.ioctl(self.fd, MODE_IOCTL, struct.pack('<I', value))
    def close(self):
        # Driver release queues black even if the previous frame swap is pending.
        os.close(self.fd)

class MaskDisplay(object):
    def __init__(self, enabled=False, device='/dev/gesture-mask-display', hz=5.0,
                 _backend_factory=None):
        if not (0 < hz <= 5.0):
            raise ValueError('HDMI rate must be >0 and <=5 Hz')
        self.enabled = bool(enabled)
        self.period = 1.0/hz
        self.next_submit = 0.0
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.stop = threading.Event()
        self.slot = None
        self.durations = collections.deque(maxlen=4096)
        self.counts = dict(accepted=0, written=0, replaced=0, busy_drops=0,
                           lock_drops=0, rate_skips=0, invalid=0, exceptions=0)
        self.error = None
        self.last_hardware_status = None
        self.factory = _backend_factory or (lambda: DeviceBackend(device))
        self.thread = None
        if self.enabled:
            self.thread = threading.Thread(target=self._run, name='mask-display')
            self.thread.daemon = True
            try:
                self.thread.start()
            except Exception as exc:
                self.error = 'start: ' + repr(exc)
                self.counts['exceptions'] += 1
                self.enabled = False
                self.stop.set()
                self.thread = None

    def submit(self, mask):
        """Call immediately after process(frame), BEFORE masks can be mutated.
        Exact 240x320 uint8 only; no resizing/thresholding or aliasing.
        Returns admission to latest slot, not physical-display success.
        """
        if not self.enabled or self.stop.is_set():
            return False
        start = time.monotonic()
        if start < self.next_submit:
            self.counts['rate_skips'] += 1
            return False
        self.next_submit = start + self.period
        if not self.lock.acquire(False):
            self.counts['lock_drops'] += 1
            return False
        try:
            if (getattr(mask, 'shape', None) != (240, 320) or
                    str(getattr(mask, 'dtype', '')) != 'uint8'):
                self.counts['invalid'] += 1
                return False
            # Single small C-order immutable snapshot; never passes NumPy pointers.
            snapshot = mask.tobytes(order='C')
            if len(snapshot) != 76800:
                self.counts['invalid'] += 1
                return False
            if self.slot is not None:
                self.counts['replaced'] += 1
            self.slot = snapshot
            self.counts['accepted'] += 1
            self.event.set()
            return True
        except Exception as exc:
            self.counts['exceptions'] += 1
            self.error = 'submit: ' + repr(exc)
            self.enabled = False
            self.stop.set()
            self.event.set()
            return False
        finally:
            self.lock.release()
            self.durations.append((time.monotonic()-start)*1000.0)

    def _run(self):
        backend = None
        try:
            backend = self.factory()
            while not self.stop.is_set():
                self.event.wait(0.1)
                with self.lock:
                    snapshot = self.slot
                    self.slot = None
                    self.event.clear()
                if snapshot is None or self.stop.is_set():
                    continue
                try:
                    backend.write(snapshot)
                    self.counts['written'] += 1
                    # Status sampling is only worker IO, never recognition thread IO.
                    self.last_hardware_status = backend.status()
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EBUSY):
                        self.counts['busy_drops'] += 1
                        continue
                    raise
        except Exception as exc:
            self.counts['exceptions'] += 1
            self.error = 'worker: ' + repr(exc)
            self.enabled = False
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception as exc:
                    self.error = 'close: ' + repr(exc)
            self.enabled = False
            with self.lock:
                self.slot = None

    def stats(self):
        result = dict(self.counts)
        samples = list(self.durations)  # call from recognition/control thread
        result.update(submit_ms_p50=percentile(samples, .50),
                      submit_ms_p95=percentile(samples, .95),
                      error=self.error, hardware_status=self.last_hardware_status,
                      worker_alive=bool(self.thread and self.thread.is_alive()))
        return result

    def close(self):
        self.enabled = False
        self.stop.set()
        self.event.set()
        if self.thread:
            self.thread.join(0.25)  # bounded shutdown; never waits in submit()
        result = self.stats()
        result['shutdown_unconfirmed'] = result['worker_alive']
        return result
