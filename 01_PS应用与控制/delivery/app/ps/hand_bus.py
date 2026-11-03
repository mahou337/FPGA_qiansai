"""SCS0009 protocol v1, big-endian words. Python 3.5; no third-party packages.
Conversions match rustypot 1.10.0 src/servo/feetech/scs0009.rs.
Only RAM goal/speed/torque writes are supported: never IDs, EEPROM or baudrate.
"""
import errno
import math
import os
from pathlib import Path
from hand_endpoints import check_raw, SPEED_RADIANS
import select
import stat
import struct
import time

try:
    import fcntl
    import termios
except ImportError:
    fcntl=termios=None

IDS = tuple(range(1, 9))


def packet(sid, instruction, params=b''):
    if not 0 <= sid <= 254 or len(params) > 250:
        raise ValueError('Invalid packet')
    body = bytes(bytearray([sid, len(params) + 2, instruction])) + params
    return b'\xff\xff' + body + bytes(bytearray([(~sum(bytearray(body))) & 255]))


def angle_raw(degrees):
    if not math.isfinite(degrees):
        raise ValueError('Nonfinite angle')
    raw = int(round(1024.0 * degrees / 300.0 + 511.0))
    if not 0 <= raw <= 1023:raise ValueError('Angle outside encoder range')
    return raw


def raw_angle(raw):
    if not 0 <= raw <= 1023:
        raise ValueError('Bad position')
    return 300.0 * (raw - 511) / 1024.0


def speed_raw(radians_per_second):
    if not math.isfinite(radians_per_second) or not .1 <= radians_per_second <= SPEED_RADIANS:
        raise ValueError('Speed must be 0.1..{} rad/s'.format(SPEED_RADIANS))
    return int(radians_per_second / (math.radians(300.0) / 1024.0))


def word(value):
    return struct.pack('>H', value)


def sync_packet(address, values):
    if address not in (40, 42, 46):
        raise ValueError('RAM write whitelist')
    if set(values) != set(IDS):
        raise ValueError('All eight servos required for synchronized command')
    width = 1 if address == 40 else 2
    params = bytes(bytearray([address, width]))
    for sid in IDS:
        value = values[sid]
        if address == 40 and value not in (0, 1):
            raise ValueError('Only torque off=0/on=1 supported')
        if address == 42:
            check_raw(sid, value)
        if address == 46 and not 1 <= value <= speed_raw(SPEED_RADIANS):
            raise ValueError('Speed outside limits; zero can mean unlimited')
        params += bytes(bytearray([sid])) + (bytes(bytearray([value])) if width == 1 else word(value))
    return packet(254, 0x83, params)


def verify_uart_identity(device='/dev/ttyPS1', sysroot='/sys', procroot='/proc'):
    # Do not accept an arbitrary serial name or console UART.
    if device != '/dev/ttyPS1':
        raise RuntimeError('Only the audited /dev/ttyPS1 path is allowed')
    name = Path(device).name
    base = Path(sysroot)
    node = base/'class/tty'/name/'device/of_node'
    if not node.exists() or node.resolve().name != 'serial@e0001000':
        raise RuntimeError('ttyPS1 is not verified PS UART1 at e0001000')
    reg = (node/'reg').read_bytes()
    if len(reg) != 8 or struct.unpack('>II', reg) != (0xe0001000, 0x1000):
        raise RuntimeError('Wrong UART register mapping')
    dt = base/'firmware/devicetree/base'
    if (dt/'gesture-hand,hardware-id').read_bytes().rstrip(b'\x00') != b'uart1-emio-f18-e18-20261101':
        raise RuntimeError('Wrong UART1 hardware candidate')
    aliases = dt/'aliases'
    for alias, expected in [('serial0', '/amba/serial@e0000000'),
                            ('serial1', '/amba/serial@e0001000')]:
        if (aliases/alias).read_bytes().rstrip(b'\x00').decode('ascii') != expected:
            raise RuntimeError('Unexpected device-tree serial alias')
    if (node/'status').read_bytes().rstrip(b'\x00') != b'okay':
        raise RuntimeError('UART1 is disabled')
    chosen = (dt/'chosen/stdout-path').read_bytes().rstrip(b'\x00').decode('ascii')
    cmdline = (Path(procroot)/'cmdline').read_text()
    if chosen != 'serial0:115200n8' or any(x in cmdline for x in ('console=ttyPS1', 'earlycon=cdns,0xe0001000')):
        raise RuntimeError('UART1 must never be a Linux console')
    return {'device': device, 'address': '0xe0001000', 'console': chosen}


class SerialBus(object):
    def __init__(self, device='/dev/ttyPS1', timeout=.035):
        import platform
        if os.geteuid() != 0 or not platform.machine().startswith('arm') or platform.release() != '4.19.0-xilinx-v2019.1':
            raise RuntimeError('Actuator connection only on audited ARM target')
        self.identity = verify_uart_identity(device)
        self.fd = None
        self.lock = None
        self.timeout = timeout
        try:
            self.lock = os.open('/run/gesture-hand-uart1.lock', os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
            fcntl.flock(self.lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.fd = os.open(device, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK|os.O_NOFOLLOW)
            if not stat.S_ISCHR(os.fstat(self.fd).st_mode):
                raise RuntimeError('UART must be character device')
            fcntl.flock(self.fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = 0; attrs[1] = 0; attrs[3] = 0
            attrs[2] = termios.CS8|termios.CREAD|termios.CLOCAL
            attrs[4] = attrs[5] = termios.B1000000
            attrs[6][termios.VMIN] = 0; attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            actual = termios.tcgetattr(self.fd)
            if actual[4:6] != [termios.B1000000, termios.B1000000]:
                raise RuntimeError('Baud readback mismatch: expected {}, actual {}'.format(termios.B1000000,actual[4:6]))
            if actual[2] & (termios.PARENB|termios.CSTOPB|getattr(termios,'CRTSCTS',0)):
                raise RuntimeError('Expected 8N1 without flow control')
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except BaseException:
            self.close(); raise

    def send(self, data):
        deadline = time.monotonic() + self.timeout
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise RuntimeError('UART transmit timeout')
            try:
                n = os.write(self.fd, data)
            except OSError as exc:
                if exc.errno == errno.EAGAIN: continue
                raise
            if n <= 0: raise RuntimeError('UART closed')
            data = data[n:]

    def request(self, sid, instruction, params, count):
        if sid not in IDS or instruction not in (1, 2):
            raise ValueError('Only ping/read unicast requests allowed')
        termios.tcflush(self.fd, termios.TCIFLUSH)
        self.send(packet(sid, instruction, params))
        deadline = time.monotonic() + self.timeout
        buf = b''
        while time.monotonic() < deadline:
            if not select.select([self.fd], [], [], max(0, deadline-time.monotonic()))[0]: break
            part = os.read(self.fd, 256)
            if not part: continue
            buf += part
            if len(buf) > 512: raise RuntimeError('Unbounded UART noise')
            while len(buf) >= 4:
                k = buf.find(b'\xff\xff')
                if k < 0: buf = buf[-1:]; break
                if k: buf = buf[k:]
                if len(buf) < 4: break
                length = buf[3]
                if not 2 <= length <= 32: buf = buf[1:]; continue
                if len(buf) < length+4: break
                frame, buf = buf[:length+4], buf[length+4:]
                if frame[2] != sid or sum(bytearray(frame[2:])) & 255 != 255:
                    raise RuntimeError('Servo response ID/checksum mismatch')
                if frame[4] != 0:
                    raise RuntimeError('Servo {} reports error {}'.format(sid, frame[4]))
                if len(frame[5:-1]) != count:
                    raise RuntimeError('Servo response size mismatch')
                return frame[5:-1]
        raise RuntimeError('Servo {} response timeout'.format(sid))

    def read(self, sid, address, count):
        return self.request(sid, 2, bytes(bytearray([address, count])), count)

    def probe(self):
        result = {}
        for sid in IDS:
            self.request(sid, 1, b'', 0)
            result[sid] = self.feedback(sid)
            result[sid]['torque'] = self.read(sid, 40, 1)[0]
        return result

    def feedback(self, sid):
        data = self.read(sid, 56, 8)
        raw = struct.unpack('>H', data[:2])[0]
        load = struct.unpack('>H', data[4:6])[0] & 0x3ff
        return {'raw': raw, 'angle': raw_angle(raw), 'load_raw': load,
                'voltage': data[6]/10.0, 'temperature': data[7]}

    def torque(self, enabled):
        self.send(sync_packet(40, dict((sid, int(enabled)) for sid in IDS)))

    def goals(self, values):
        self.send(sync_packet(42, dict((sid, angle_raw(values[sid])) for sid in IDS)))

    def speed(self, radians=SPEED_RADIANS):
        self.send(sync_packet(46, dict((sid, speed_raw(radians)) for sid in IDS)))

    def close(self):
        if self.fd is not None:
            try: fcntl.ioctl(self.fd, termios.TIOCNXCL)
            except OSError: pass
            os.close(self.fd); self.fd = None
        if self.lock is not None:
            os.close(self.lock); self.lock = None
