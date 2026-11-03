"""ASCII CRC16-CCITT-FALSE telemetry. Four bits: thumb,index,middle,ring."""
import binascii
import time
STATUSES = {'NO_HAND', 'PENDING', 'UNKNOWN', 'HOLD', 'PARTIAL', 'NEED_CALIBRATION', 'REACQUIRE', 'CONFIRMED', 'CAPTURE_ERROR', 'STOPPED', 'CALIBRATING', 'STALE'}

def code_ok(code):
    return len(code) == 4 and set(code) <= set('01?')

def encode(seq, milliseconds, result, source='LIVE'):
    status = result['status'].replace(' ', '_')
    raw = result.get('raw', {}).get('code', '????')
    stable = result.get('code', '????')
    if status not in STATUSES or not code_ok(raw) or (not code_ok(stable)):
        raise ValueError('Bad recognition result')
    valid = source == 'LIVE' and status == 'CONFIRMED' and result.get('reliable', False) and ('?' not in raw) and (raw == stable)
    event = valid and result.get('command_ready', False)
    payload = 'G1,{0},{1},{2},{3},{4},{5},{6},{7}'.format(seq, milliseconds, source, raw, stable, status, int(valid), int(event)).encode('ascii')
    crc = binascii.crc_hqx(payload, 65535)
    return b'$' + payload + '*{0:04X}\r\n'.format(crc).encode('ascii')

def decode(line):
    if len(line) > 180 or not line.endswith(b'\r\n') or (not line.startswith(b'$')):
        raise ValueError('Bad framing')
    try:
        payload, checksum = line[1:-2].rsplit(b'*', 1)
        if len(checksum) != 4 or int(checksum, 16) != binascii.crc_hqx(payload, 65535):
            raise ValueError('CRC mismatch')
        version, seq, ms, source, raw, stable, status, valid, event = payload.decode('ascii').split(',')
        if version != 'G1' or source not in ('LIVE', 'REPLAY') or status not in STATUSES or (not code_ok(raw)) or (not code_ok(stable)) or (valid not in ('0', '1')) or (event not in ('0', '1')):
            raise ValueError('Invalid fields')
        if int(seq) < 0 or int(ms) < 0:
            raise ValueError('Negative counter')
        if valid == '1' and (source != 'LIVE' or status != 'CONFIRMED' or '?' in raw or (raw != stable)):
            raise ValueError('Invalid authorization')
        if event == '1' and valid != '1':
            raise ValueError('Event without valid')
        return dict(seq=int(seq), ms=int(ms), source=source, raw=raw, code=stable, status=status, valid=valid == '1', event=event == '1')
    except (UnicodeError, TypeError) as exc:
        raise ValueError('Malformed record') from exc

class Receiver:
    """Bounded streaming parser. Duplicate/out-of-order packets cannot renew validity."""

    def __init__(self, timeout=1.0):
        self.buffer = bytearray()
        self.last = None
        self.last_time = None
        self.timeout = timeout
        self.errors = 0

    def feed(self, data, now=None):
        now = time.monotonic() if now is None else now
        self.buffer.extend(data)
        records = []
        while b'\n' in self.buffer:
            end = self.buffer.index(10) + 1
            line = bytes(self.buffer[:end])
            del self.buffer[:end]
            pos = line.rfind(b'$')
            if pos >= 0:
                line = line[pos:]
            try:
                record = decode(line)
                if self.last and record['seq'] <= self.last['seq']:
                    raise ValueError('Duplicate or out of order; restart receiver for new sender session')
            except ValueError:
                self.errors += 1
                continue
            self.last, self.last_time = (record, now)
            records.append(record)
        if len(self.buffer) > 180:
            self.buffer.clear()
            self.errors += 1
        return records

    def is_valid(self, now=None):
        now = time.monotonic() if now is None else now
        return bool(self.last and self.last['valid'] and (now - self.last_time <= self.timeout))
