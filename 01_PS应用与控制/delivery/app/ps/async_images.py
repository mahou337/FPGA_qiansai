"""Bounded diagnostic worker. Python 3.5; no hardware/recognizer access."""
import copy
import collections
import json
import os
import queue
import threading
import time
from finger_detection import draw_finger_detection
from stage2_io import json_text

class AsyncImages(object):
    def __init__(self, store, config, interval=1.0):
        self.store, self.config, self.interval = store, copy.deepcopy(config), interval
        self.queue = queue.Queue(maxsize=1)  # one queued + one in-flight snapshot
        self.stop = threading.Event()
        self.accepted = self.completed = self.failed = 0
        self.skipped = collections.Counter()
        self.last_submit = None
        self.error = None
        self.thread = threading.Thread(target=self._worker, name='diagnostic-images')
        self.thread.daemon = True
        self.thread.start()

    def submit(self, index, full, frame, masks, palm, features, result, metadata, now=None):
        now = time.monotonic() if now is None else now
        reason = None
        if self.stop.is_set() or self.error is not None:
            reason = 'worker_disabled'
        elif self.accepted >= self.store.max_saved:
            reason = 'image_count_limit'
        elif self.last_submit is not None and now-self.last_submit < self.interval:
            reason = 'rate_limited'
        elif self.queue.full():
            reason = 'queue_full'
        if reason:
            self.skipped[reason] += 1
            return {'saved':False,'queued':False,'reason':reason}
        # Never enqueue references that the capture/recognizer can mutate.
        job = (index, full.copy(), frame.copy(),
               {k:masks[k].copy() for k in ('skin_mask','clean_mask','final_hand_mask',
                                           'palm_edges','palm_new_edges','palm_edge_overlay') if k in masks},
               copy.deepcopy(palm), copy.deepcopy(features), copy.deepcopy(result),
               copy.deepcopy(metadata))
        try:
            self.queue.put_nowait(job)
        except queue.Full:
            self.skipped['queue_full'] += 1
            return {'saved':False,'queued':False,'reason':'queue_full'}
        self.accepted += 1
        self.last_submit = now
        return {'saved':False,'queued':True,'reason':'async_queued',
                'job_frame_index':index,'completion_log':'image_results.jsonl'}

    def _worker(self):
        stream = None
        try:
            stream = open(str(self.store.directory/'image_results.jsonl'),'x',encoding='utf-8')
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    job = self.queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                index, full, frame, masks, palm, features, result, metadata = job
                started = time.monotonic()
                try:
                    annotation = draw_finger_detection(frame,palm,features,result,self.config)
                    saved = self.store.save_images(index,full,frame,masks,annotation)
                    record = dict(frame_index=index,images=saved,metadata=metadata,
                                  worker_ms=(time.monotonic()-started)*1000)
                    text = json_text(record)+'\n'
                    self.store.reserve(len(text.encode('utf-8')))
                    stream.write(text);stream.flush();os.fsync(stream.fileno())
                    self.completed += int(saved.get('saved',False))
                finally:
                    self.queue.task_done()
        except Exception as exc:
            self.failed += 1
            self.error = str(exc)
            self.stop.set()
        finally:
            if stream is not None:
                try:
                    stream.flush();os.fsync(stream.fileno());stream.close()
                except Exception as exc:
                    self.error = str(exc)

    def close(self, timeout=5.0):
        self.stop.set()
        self.thread.join(timeout)
        alive = self.thread.is_alive()
        if alive:
            while True:
                try:
                    self.queue.get_nowait(); self.queue.task_done()
                except queue.Empty:
                    break
            self.error = self.error or 'IMAGE_WORKER_SHUTDOWN_TIMEOUT'
        return dict(accepted=self.accepted,completed=self.completed,failed=self.failed,
                    skipped=dict(self.skipped),error=self.error,worker_alive=alive,
                    incomplete=max(0,self.accepted-self.completed),
                    max_queued=1,max_inflight=1,min_interval_seconds=self.interval)
