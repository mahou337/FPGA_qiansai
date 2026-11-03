"""Hold an exclusive application/update lock across exec; foreground only."""
import fcntl
import os
from pathlib import Path
import sys
ROOT=Path('/opt/gesture-recognition-stage2')
if __name__=='__main__':
    lock=os.open(str(ROOT/'operation.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError: raise SystemExit('Another stage2 app/update is active; stop it first')
    os.set_inheritable(lock,True)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    entry=Path(__file__).resolve().parent/'ps/run.py'
    os.execv(sys.executable,[sys.executable,str(entry)]+sys.argv[1:])
