# Independent launcher; original delivery and its manifest remain unchanged.
from pathlib import Path
import sys
_delivery = Path(__file__).resolve().parent / 'delivery'
sys.path.insert(0, str(_delivery))
__file__ = str(_delivery / 'start_follow.py')
"""Explicit local FOLLOW_FINAL authorization; no automatic motion at installation."""
import json,os,sys,time,signal
from pathlib import Path
from verify_files import verify

def emit(name,**fields):print(json.dumps(dict(event=name,**fields)),flush=True)

def confirm_interactive(prompt,timeout=60.0):
    """Fresh TTY-only acknowledgement. Blank lines never authorize motion."""
    import select,termios
    fd=sys.stdin.fileno()
    if not os.isatty(fd):
        raise RuntimeError('Interactive terminal required; piped confirmation refused')
    if not termios.tcgetattr(fd)[3] & termios.ICANON:
        raise RuntimeError('Canonical terminal input required; no terminal settings changed')
    # Discard only pre-existing console input, never alter servo UART settings.
    termios.tcflush(fd,termios.TCIFLUSH)
    deadline=time.monotonic()+timeout
    print(prompt,end='',flush=True)
    line=bytearray()
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            emit('CONFIRM_TIMEOUT_NO_WRITES')
            return ''
        ready,unused,unused2=select.select([fd],[],[],remaining)
        if not ready:
            emit('CONFIRM_TIMEOUT_NO_WRITES')
            return ''
        data=os.read(fd,1)
        if not data:
            raise EOFError('Terminal input ended; no authorization')
        if data in (b'\r',b'\n'):
            value=bytes(line).decode('ascii');line=bytearray()
            if not value.strip():
                emit('EMPTY_INPUT_IGNORED',note='Still waiting for the exact confirmation word shown above; no writes authorized')
                print(prompt,end='',flush=True)
                continue
            return value
        line.extend(data)
        if len(line)>128:
            raise RuntimeError('Confirmation input too long; no authorization')


def stop(signum,frame):raise KeyboardInterrupt('Operator stop')

def main():
    for n in ('SIGINT','SIGTERM','SIGHUP'):
        signal.signal(getattr(signal,n),stop)
    verify()
    test=sys.argv[1:]==['--confirm-test']
    if sys.argv[1:] and not test:raise RuntimeError('No extra motion arguments allowed')
    print('FOLLOW_FINAL: REAL four-finger motion on ONE complete new raw frame. PENDING uses current raw.')
    print('User-confirmed individual endpoints; 1=straight, 0=bent; MaxSpeed=5 rad/s parameter (raw 977), NOT measured speed.')
    print('WARNING: speed parameter is 20x the original 0.25 setting; recognition/communication faults remain unresolved.')
    print('Mount base firmly; hand empty; no touching; physical power cutoff ready.')
    print('Stop other recognition/diagnostic programs. Q or Ctrl+C requests torque-off.')
    token=confirm_interactive('Type FOLLOW_FINAL then Enter to authorize direct endpoint following: ')
    if token!='FOLLOW_FINAL':
        emit('CANCELLED_NO_WRITES');return 1
    if test:
        emit('CONFIRM_INPUT_TEST',matched=True,servo_uart_opened=False,servo_writes=False);return 0
    os.environ['GESTURE_HAND_FINAL_ACK']='FOLLOW_FINAL'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    launch=Path(__file__).resolve().parent/'app/launch.py'
    os.execv(sys.executable,[sys.executable,'-B',str(launch),'--hardware','--automatic','--hand','--no-images','--hdmi','--hdmi-hz','5','--max-mib','256'])

if __name__=='__main__':
    try:sys.exit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('FOLLOW_FINAL_REFUSED: '+str(exc),file=sys.stderr);sys.exit(1)
