"""Non-blocking local IPC from recognition to separate actuator watchdog process."""
import fcntl
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time


class HandBridge(object):
    def __init__(self, directory):
        self.child=None;self.errors=None
        self.release_verified=False;self.exit_status=None;self.exit_collected=False
        try:
            self.errors=open(str(Path(directory)/'hand_stderr.log'),'xb')
            self.child=subprocess.Popen([sys.executable,str(Path(__file__).with_name('hand_worker.py')),
                '--worker','--log',str(Path(directory)/'hand_events.jsonl')],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,close_fds=True)
            if not select.select([self.child.stdout],[],[],8)[0] or self.child.stdout.readline()!=b'READY\n':
                raise RuntimeError('Hand preflight failed; inspect hand_stderr.log and hand_events.jsonl')
            fd=self.child.stdin.fileno()
            fcntl.fcntl(fd,fcntl.F_SETFL,fcntl.fcntl(fd,fcntl.F_GETFL)|os.O_NONBLOCK)
        except BaseException:
            self.close();raise

    def collect_exit_status(self):
        if self.exit_collected or self.child is None or self.child.poll() is None:
            return
        self.exit_collected=True
        # Child has exited. Its only stdout after READY is one bounded JSON ack.
        try:data=self.child.stdout.read(4097)
        except (OSError,IOError):return
        if len(data)>4096:return
        for line in data.splitlines():
            try:status=json.loads(line.decode('ascii'))
            except (ValueError,UnicodeError):continue
            if (isinstance(status,dict) and status.get('kind')=='HAND_EXIT' and
                    type(status.get('return_code')) is int and
                    status['return_code']==self.child.returncode and
                    type(status.get('release_verified')) is bool):
                self.exit_status=status
                self.release_verified=status['release_verified']

    def submit(self, packet, captured):
        if self.child.poll() is not None:
            self.collect_exit_status()
            detail=(self.exit_status or {}).get('error') or 'exit code {}'.format(self.child.returncode)
            state='torque-off verified' if self.release_verified else 'release unconfirmed; cut servo power'
            raise RuntimeError('Actuator exited: {}; {}'.format(detail,state))
        data=(json.dumps({'frame':packet.decode('ascii'),'captured':captured,'sent':time.monotonic()},
                         separators=(',',':'))+'\n').encode('ascii')
        if len(data)>1024:raise RuntimeError('Unexpected IPC record size')
        # Under PIPE_BUF: one nonblocking write is atomic; full pipe is a fault.
        n=os.write(self.child.stdin.fileno(),data)
        if n!=len(data):raise RuntimeError('Incomplete actuator IPC write')

    def close(self):
        rc=0
        if self.child is not None:
            if self.child.stdin:
                try:self.child.stdin.close()
                except OSError:pass
            try:self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:self.child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    print('HAND PROCESS STUCK: CUT SERVO POWER',file=sys.stderr)
                    self.child.kill();self.child.wait()
            self.collect_exit_status()
            rc=self.child.returncode
            if self.child.stdout:self.child.stdout.close()
            self.child=None
        if self.errors:self.errors.close();self.errors=None
        return rc
