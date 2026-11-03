"""Verified-register access, SCCB setup, and frozen snapshot acquisition."""
import ctypes as C
import json
import os
import time
from pathlib import Path
import cv2
import numpy as np

class Hardware:
    def __init__(self, base=0x40000000, device='/dev/mem', library=None):
        lib = library or str(Path(__file__).with_name('libgesture_mmio.so'))
        self.lib = C.CDLL(lib, use_errno=True)
        self.lib.gesture_open.argtypes = [C.c_char_p, C.c_uint64]
        self.lib.gesture_open.restype = C.c_void_p
        self.lib.gesture_close.argtypes = [C.c_void_p]
        self.lib.gesture_read.argtypes = [C.c_void_p, C.c_uint32]
        self.lib.gesture_read.restype = C.c_uint32
        self.lib.gesture_write.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32]
        self.lib.gesture_copy.argtypes = [C.c_void_p, C.POINTER(C.c_uint32), C.c_uint32]
        self.handle = self.lib.gesture_open(device.encode(), base)
        if not self.handle: raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        try:
            if self.read(0) != 0x47535431: raise RuntimeError('Wrong PL image/peripheral ID')
            if self.read(0x18) != (240<<16)|320: raise RuntimeError('Unexpected capture dimensions')
            if self.read(12) & 2: raise RuntimeError('Capture still busy; reset PL before restart')
        except Exception:
            self.close(); raise
        self.control = self.read(4)
        self.words = np.empty(38400, dtype=np.uint32)

    def read(self, offset): return self.lib.gesture_read(self.handle, offset)
    def write(self, offset, value):
        if self.lib.gesture_write(self.handle, offset, value) != 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
    def close(self):
        if self.handle:
            self.lib.gesture_close(self.handle); self.handle = None

    def pins(self, scl=None, sda=None, reset_n=None, pwdn=None):
        # scl/sda: 1 releases open drain; 0 drives low.
        for bit, value in ((0, reset_n), (1, pwdn), (2, None if scl is None else 1-scl),
                           (3, None if sda is None else 1-sda)):
            if value is not None: self.control = (self.control & ~(1<<bit)) | (int(value)<<bit)
        self.write(4, self.control)
        time.sleep(.00001)
        if scl == 1:
            end = time.monotonic()+.02
            while not self.read(12) & 8:
                if time.monotonic()>end: raise TimeoutError('SCCB SCL stuck low')
                time.sleep(.00001)

    def start(self):
        self.pins(scl=0, sda=1); self.pins(scl=1); self.pins(sda=0); self.pins(scl=0)
    def stop(self):
        self.pins(scl=0, sda=0); self.pins(scl=1); self.pins(sda=1)
    def send(self, value):
        for shift in range(7,-1,-1):
            self.pins(scl=0, sda=(value>>shift)&1); self.pins(scl=1); self.pins(scl=0)
        self.pins(sda=1); self.pins(scl=1)
        ack = not bool(self.read(12)&16)
        self.pins(scl=0)
        if not ack: raise OSError('SCCB NACK for byte 0x{0:02x}'.format(value))
    def receive(self):
        value = 0; self.pins(sda=1)
        for _ in range(8):
            self.pins(scl=1); value=(value<<1)|int(bool(self.read(12)&16)); self.pins(scl=0)
        self.pins(sda=1); self.pins(scl=1); self.pins(scl=0)  # NACK final byte
        return value
    def camera_write(self, address, value):
        try:
            self.start()
            for b in (0x78,address>>8,address&255,value): self.send(b)
        except Exception as exc:
            raise OSError('SCCB write reg 0x{0:04X}, value 0x{1:02X}: {2}'.format(address, value, exc)) from exc
        finally: self.stop()
    def camera_read(self, address):
        try:
            self.start()
            for b in (0x78,address>>8,address&255): self.send(b)
            self.stop(); self.start(); self.send(0x79)
            return self.receive()
        except Exception as exc:
            raise OSError('SCCB read reg 0x{0:04X}: {1}'.format(address, exc)) from exc
        finally: self.stop()

    def initialize(self, table):
        self.pins(reset_n=0, pwdn=1, scl=1, sda=1); time.sleep(.02)
        self.pins(pwdn=0); time.sleep(.01)
        self.pins(reset_n=1); time.sleep(.02)
        # Recover a transaction interrupted before the host restarted.
        for _ in range(9): self.pins(scl=0); self.pins(scl=1)
        self.stop()
        chip = (self.camera_read(0x300a)<<8)|self.camera_read(0x300b)
        reporter = getattr(self, 'report_sensor_id', None)
        if callable(reporter): reporter(chip)
        if chip != 0x5640: raise RuntimeError('Expected OV5640, found 0x{0:04X}'.format(chip))
        config = json.loads(Path(table).read_text())
        for row in config['base_registers']+config['overrides']:
            self.camera_write(int(row['address'],16), int(row['value'],16))
            if row['delay_ms']: time.sleep(row['delay_ms']/1000)
        # Verify the final programmed clock tree as well as output geometry.
        if "clock" in config:
            final = {int(r["address"],16):int(r["value"],16) for r in config["base_registers"]+config["overrides"]}
            for address in (0x3034,0x3035,0x3036,0x3037,0x3108,0x460c,0x3824):
                if self.camera_read(address) != final[address]:
                    raise RuntimeError('Camera clock readback mismatch at {0:04X}'.format(address))
        width, height = config.get("width", 320), config.get("height", 240)
        for a, expected in ((0x3808,width>>8),(0x3809,width&255),(0x380a,height>>8),(0x380b,height&255),
                            (0x4300,0x61),(0x501f,1),(0x4740,0x20)):
            actual = self.camera_read(a)
            if actual != expected: raise RuntimeError('Camera readback {0:04X}: {1:02X} != {2:02X}'.format(a, actual, expected))

    def capture(self, timeout=1.0):
        if self.read(12)&2: raise RuntimeError('Capture busy; reset PL after an interrupted acquisition')
        old_seq = self.read(16)
        self.write(8,1)
        end = time.monotonic()+timeout
        while self.read(16)==old_seq:
            if time.monotonic()>end:
                raise TimeoutError('No completed frame; inspect PCLK/VSYNC/HREF and reset PL before retry')
            time.sleep(.001)
        status = self.read(12)
        if (status&7)!=1: raise RuntimeError('Malformed camera frame, status=0x{0:08X}'.format(status))
        if self.lib.gesture_copy(self.handle,self.words.ctypes.data_as(C.POINTER(C.c_uint32)),38400):
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        # FPGA writes low pixel first. Host is little-endian ARMv7; BGR565 decoder
        # interprets B[4:0], G[10:5], R[15:11], zero-filling low colour bits.
        image = cv2.cvtColor(self.words.view(np.uint8).reshape(240,320,2), cv2.COLOR_BGR5652BGR)
        return self.read(16), image
