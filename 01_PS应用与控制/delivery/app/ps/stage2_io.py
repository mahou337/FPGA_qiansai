"""Bounded diagnostics and an explicitly owned foreground terminal. Python 3.5."""
import collections
import json
import os
from pathlib import Path
import select
import sys
import time
import uuid
import threading
import cv2
import numpy as np
from stage1_camera_test import check_storage


def json_default(value):
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    raise TypeError('Not JSON serializable: ' + type(value).__name__)


def json_text(value):
    return json.dumps(value, default=json_default, sort_keys=True, ensure_ascii=True, allow_nan=False)


def read_png(path):
    data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None: raise ValueError('Cannot decode PNG: ' + str(path))
    return image


def preprocess(image, orientation=0):
    if image is None or image.dtype != np.uint8 or image.shape != (480,640,3):
        raise ValueError('Input must be a full 640x480 uint8 BGR frame')
    if orientation not in (0,180): raise ValueError('Only 0 or 180 degrees are supported')
    oriented = image if orientation == 0 else cv2.flip(image, -1)
    return cv2.resize(oriented, (320,240), interpolation=cv2.INTER_AREA)


class RunStore(object):
    def __init__(self, root, live, max_bytes=128*1024*1024, max_saved=100, min_free=32*1024*1024):
        self.root = Path(root)
        self.live, self.max_bytes, self.max_saved, self.min_free = live, max_bytes, max_saved, min_free
        self.bytes, self.saved = 0, 0
        self.budget_lock = threading.Lock()
        self.storage = check_storage(self.root) if live else {'scope':'offline_replay_only'}
        parent = self.root / 'gesture-tests' if live else self.root
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = parent / ('run-' + uuid.uuid4().hex)
        self.directory.mkdir()
        self.frames = open(str(self.directory/'frames.jsonl'), 'x', encoding='utf-8')
        self.log = open(str(self.directory/'run.log'), 'x', encoding='utf-8')
        self.protocol = open(str(self.directory/'protocol.g1'), 'xb')
        self.windows = {}
        self.cycles = 0
        self.cycle_seconds = 0.0

    def space(self, needed=0):
        if self.bytes + needed > self.max_bytes - 1024*1024:
            raise IOError('RUN_CAPACITY_LIMIT: bounded run capacity exhausted; stop safely')
        if self.live:
            # Check mount identity throughout a run, not just at startup.
            info = check_storage(self.root)
            if info['available_bytes'] < self.min_free + needed:
                raise IOError('SD_LOW_SPACE: reserve reached; stop safely')

    def reserve(self, needed):
        # No encoding, fsync or file writes while holding this short lock.
        # Check media first; re-check accounting atomically against the worker.
        self.space(needed)
        with self.budget_lock:
            if self.bytes + needed > self.max_bytes - 1024*1024:
                raise IOError('RUN_CAPACITY_LIMIT: bounded run capacity exhausted; stop safely')
            self.bytes += needed

    def metadata(self, name, data):
        text = json_text(data)+'\n'
        self.reserve(len(text.encode('utf-8')))
        with open(str(self.directory/name), 'x', encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())

    def event(self, message):
        text = '[{0:.6f}] {1}\n'.format(time.monotonic(), message)
        self.reserve(len(text.encode('utf-8')))
        self.log.write(text); self.log.flush()

    def packet(self, packet):
        self.reserve(len(packet)); self.protocol.write(packet); self.protocol.flush()

    def record(self, row):
        text=json_text(row)+'\n'; self.reserve(len(text.encode('utf-8')))
        self.frames.write(text); self.frames.flush()

    def save_images(self, frame_id, full, frame, masks, annotation):
        if self.saved >= self.max_saved: return {'saved':False,'reason':'image_count_limit'}
        images={'raw_640x480':full, 'input_320x240':frame,
                'skin_mask':masks['skin_mask'],'clean_mask':masks['clean_mask'],
                'final_hand_mask':masks['final_hand_mask'],'annotated':annotation}
        for key in ('palm_edges','palm_new_edges','palm_edge_overlay'):
            if key in masks: images[key] = masks[key]
        encoded=[]
        for name,image in images.items():
            ok,data=cv2.imencode('.png',image,[cv2.IMWRITE_PNG_COMPRESSION,1])
            if not ok: raise IOError('PNG_ENCODER_FAILED: '+name)
            encoded.append((name,data.tobytes()))
        self.reserve(sum(len(data) for _,data in encoded))
        folder=self.directory/('frame-{0:08d}'.format(frame_id)); folder.mkdir()
        for name,data in encoded:
            dest=folder/(name+'.png')
            with open(str(dest),'xb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
        self.saved+=1
        return {'saved':True,'directory':folder.name,'files':list(images)}

    def cycle(self, timing):
        self.cycles+=1
        self.cycle_seconds += timing.get('cycle_total_ms',0.0)/1000.0
        for key,value in timing.items():
            self.windows.setdefault(key,collections.deque(maxlen=2048)).append(float(value))

    def summary(self, values):
        values=dict(values)
        values['processing_fps_excludes_setup_and_operator_wait'] = self.cycles / self.cycle_seconds if self.cycle_seconds > 0 else None
        values['overall_fps_includes_setup_and_operator_wait'] = values.get('processed_frames',0) / values['elapsed_seconds'] if values.get('elapsed_seconds',0) > 0 else None
        values['byte_accounting'] = 'reserved upper bound including failed/partial writes; excludes summary itself'
        values.update(saved_frame_groups=self.saved,bytes_written=self.bytes,completed_cycles=self.cycles,
                      percentile_scope='last up to 2048 completed cycles; async enqueue and serial included; background image encoding/writes excluded',
                      timing_percentiles_ms={k:dict(zip(('p50','p90','p95','p99'),[float(x) for x in np.percentile(list(v),[50,90,95,99])])) for k,v in self.windows.items()},
                      stage2_board_acceptance=False,storage=self.storage)
        self.metadata('summary.json',values)

    def close(self):
        error=None
        for stream in (self.frames,self.log,self.protocol):
            try: stream.flush(); os.fsync(stream.fileno())
            except Exception as exc: error=exc
            finally: stream.close()
        if error is not None: raise error


class ForegroundTerminal(object):
    """Never opens ttyPS0 again; use the current login's foreground terminal.

Line-exact B/G/C/K/Q/EMPTY/NEXT commands only. In strict mode disable output
translation and echo, retain canonical input/signals, and restore all settings.
The parent login shell waits for this process; no getty configuration is changed.
"""
    def __init__(self, strict=False, enabled=True):
        self.strict, self.enabled = strict, enabled
        self.attrs=None; self.kernel_printk=None; self.buffer=b''; self.eof=False
        self.fd_in = sys.stdin.fileno() if enabled else None
        self.fd_out = sys.stdout.fileno()
        if strict:
            if not (os.isatty(self.fd_out) and enabled and os.isatty(self.fd_in)):
                raise RuntimeError('Strict protocol requires the current foreground login TTY')
            if os.fstat(self.fd_in).st_rdev != os.fstat(self.fd_out).st_rdev:
                raise RuntimeError('stdin/stdout must own the same terminal')
            if os.tcgetpgrp(self.fd_out) != os.getpgrp():
                raise RuntimeError('Process must own foreground terminal, not run in background')
            import termios
            self.attrs=termios.tcgetattr(self.fd_out)
            attrs=termios.tcgetattr(self.fd_out)
            attrs[1] &= ~(termios.OPOST | termios.ONLCR)
            attrs[3] &= ~(termios.ECHO | termios.ECHONL)
            attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
            attrs[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | getattr(termios,'CRTSCTS',0))
            attrs[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4]=attrs[5]=termios.B115200
            try:
                termios.tcsetattr(self.fd_out,termios.TCSANOW,attrs)
                path=Path('/proc/sys/kernel/printk')
                self.kernel_printk=path.read_text()
                fields=self.kernel_printk.split(); fields[0]='1'
                path.write_text(' '.join(fields)+'\n')
            except Exception:
                self.close(); raise

    def commands(self):
        if not self.enabled or self.eof: return []
        if not select.select([self.fd_in],[],[],0)[0]: return []
        data=os.read(self.fd_in,256)
        if not data: self.eof=True; return []
        self.buffer+=data
        if len(self.buffer)>1024: self.buffer=b''; return []
        commands=[]
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try: word=line.strip().decode('ascii').upper()
            except UnicodeError: continue
            if word in ('B','G','C','K','Q','EMPTY','NEXT'): commands.append(word)
        return commands

    def send(self, packet):
        deadline=time.monotonic()+0.5
        while packet:
            if time.monotonic()>deadline: raise TimeoutError('Foreground UART write stalled')
            if not select.select([],[self.fd_out],[],0.05)[1]: continue
            count=os.write(self.fd_out,packet)
            if count<=0: raise IOError('UART closed')
            packet=packet[count:]

    def close(self):
        errors=[]
        if self.kernel_printk is not None:
            try: Path('/proc/sys/kernel/printk').write_text(self.kernel_printk)
            except Exception as exc: errors.append(str(exc))
            self.kernel_printk=None
        if self.attrs is not None:
            import termios
            try: termios.tcsetattr(self.fd_out,termios.TCSANOW,self.attrs)
            except Exception as exc: errors.append(str(exc))
            self.attrs=None
        if errors: raise RuntimeError('Terminal restoration failed: '+ '; '.join(errors))
