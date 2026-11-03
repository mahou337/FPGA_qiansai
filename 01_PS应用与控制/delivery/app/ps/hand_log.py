"""Bounded asynchronous actuator log: SD writes never block the control loop."""
import queue
import threading

class HandLog(object):
    def __init__(self,path):
        self.file=open(path,'x',buffering=1)
        self.queue=queue.Queue(maxsize=128);self.error=None;self.count=0
        self.thread=threading.Thread(target=self._write);self.thread.daemon=True;self.thread.start()
    def _write(self):
        try:
            while True:
                text=self.queue.get()
                if text is None:break
                self.count+=len(text)
                if self.count>4*1024*1024:raise RuntimeError('Actuator log size limit reached')
                self.file.write(text);self.file.flush()
        except Exception as exc:self.error=str(exc)
        finally:self.file.close()
    def emit(self,text):
        if self.error:raise RuntimeError('Actuator log failed: '+self.error)
        try:self.queue.put_nowait(text+'\n')
        except queue.Full:raise RuntimeError('Actuator log backlog limit')
    def close(self):
        try:self.queue.put_nowait(None)
        except queue.Full:return False
        self.thread.join(timeout=1)
        return not self.thread.is_alive() and self.error is None
