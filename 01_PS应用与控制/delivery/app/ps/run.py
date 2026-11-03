"""V7 recognition with optional separately supervised PS UART1 hand controller."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import sys
import time
import cv2
import numpy as np
from headless import HeadlessRecognizer, load_config
from protocol import encode, decode
from stage2_io import ForegroundTerminal, RunStore, preprocess, read_png
from stage1_camera_test import validate_diag
from async_images import AsyncImages
from mask_display import MaskDisplay
from compat_records import asdict
from finger_detection import draw_finger_detection

APP=Path(__file__).resolve().parents[1]
STEPS=(('empty_background',None),('five_open','1111'),('thumb_bent','0111'),
       ('index_bent','1011'),('middle_bent','1101'),('ring_bent','1110'),
       ('combination_operator_selected',None),('no_hand',None),('reentry_five_open','1111'))


def invalid(status, reason=None):
    return {'status':status,'code':'????','raw':{'code':'????','reason':reason or status},
            'reliable':False,'command_ready':False}


class Guide(object):
    def __init__(self, count):
        self.index=0; self.remaining=0; self.count=count; self.waiting_reason=None
    def prompt(self):
        if self.index>=len(STEPS): return 'GUIDE COMPLETE: Q then Enter to stop; labels are operator declarations, not measured accuracy.'
        return 'GUIDE {0}/{1}: {2}. Arrange pose, then type {3} and Enter.'.format(
            self.index+1,len(STEPS),STEPS[self.index][0],'EMPTY' if self.index==0 else 'NEXT')
    def command(self, word):
        if self.index>=len(STEPS) or self.remaining: return False
        if word != ('EMPTY' if self.index==0 else 'NEXT'): return False
        self.remaining=self.count
        return True
    def label(self):
        if not self.remaining: return None
        name,code=STEPS[self.index]
        return {'origin':'operator_acknowledged_requested_pose','pose':name,
                'declared_four_bits':code,'prediction_is_not_ground_truth':True}
    def restart(self, background_ready=False):
        self.index=1 if background_ready else 0
        self.remaining=0
        self.waiting_reason=None

    def advance(self, background_ready=False, confirmed_open=False):
        if not self.remaining: return False
        self.remaining-=1
        if self.remaining: return False
        # A frame quota is not evidence that calibration succeeded.
        if self.index==0 and not background_ready:
            self.remaining=1; self.waiting_reason='background_not_ready'; return False
        if self.index==1 and (not background_ready or not confirmed_open):
            self.remaining=1; self.waiting_reason='need_CONFIRMED_1111_keep_five_fingers_open'; return False
        self.waiting_reason=None
        self.index+=1
        return True


def operator_command(command, guide, recognizer, pending_empty, message, emit):
    """One shared command state machine for guided and live modes."""
    message('INPUT_RECEIVED '+command)
    if command=='Q':
        message('INPUT_ACK Q: stopping')
        return pending_empty, True
    if command=='B':
        if guide: guide.restart(False)
        emit(invalid('CALIBRATING','awaiting_empty_scene_confirmation'))
        message('INPUT_ACK B: remove hand; type EMPTY then Enter.')
        return True, False
    if command=='EMPTY':
        if guide and guide.index==0 and not guide.remaining:
            guide.command('EMPTY')
            recognizer.command('B')
            message('INPUT_ACK EMPTY; BACKGROUND_CAPTURE_BEGIN')
            message('GUIDE_CAPTURE_BEGIN empty_background')
            # Also clear a preceding B request. v3 forgot this on the guide path.
            return False, False
        if not guide and pending_empty:
            recognizer.command('B')
            message('INPUT_ACK EMPTY; BACKGROUND_CAPTURE_BEGIN')
            return False, False
        message('INPUT_IGNORED EMPTY: capture already active or not requested; use B to restart.')
        return pending_empty, False
    if command=='NEXT':
        if guide and guide.command('NEXT'):
            message('INPUT_ACK NEXT; GUIDE_CAPTURE_BEGIN '+STEPS[guide.index][0])
        else:
            message('INPUT_IGNORED NEXT: first EMPTY, or wait for the active capture/calibration.')
        return pending_empty, False
    if command in ('G','C','K'):
        recognizer.command(command)
        if guide:
            ready=bool(recognizer.background.enabled and recognizer.background.reference is not None)
            guide.restart(ready)
            message(guide.prompt())
        emit(invalid('PENDING','operator_'+command))
        message('INPUT_ACK '+command+'; identity/debounce reset; background='+str(recognizer.background.enabled))
        return False, False
    message('INPUT_IGNORED unknown command')
    return pending_empty, False


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    src=p.add_mutually_exclusive_group(required=True)
    src.add_argument('--hardware',action='store_true')
    src.add_argument('--images',help='Directory of original 640x480 real-*.png images; REPLAY always invalid')
    p.add_argument('--pattern',default='real-*.png')
    p.add_argument('--config',default=str(APP/'config/algorithm.json'))
    p.add_argument('--camera-table',default=str(APP/'config/ov5640_vga_rgb565.json'))
    p.add_argument('--device',default='/dev/gesture-camera')
    p.add_argument('--mount',default='/mnt/sdcard')
    p.add_argument('--replay-output',help='Required for replay; never the hardware output override')
    p.add_argument('--orientation',type=int,choices=(0,180),default=0)
    p.add_argument('--frames',type=int,default=0)
    p.add_argument('--capture-timeout',type=float,default=1.0)
    p.add_argument('--save-every',type=int,default=10)
    p.add_argument('--max-saved',type=int,default=100)
    p.add_argument('--max-mib',type=int,default=128)
    p.add_argument('--image-interval',type=float,default=1.0,help='Minimum seconds between diagnostic image jobs')
    p.add_argument('--no-images',action='store_true',help='Timing mode; JSONL and G1 still recorded')
    p.add_argument('--no-input',action='store_true',help='Disable operator commands; no background is captured automatically')
    p.add_argument('--no-edge-assist',action='store_true',help='Disable interior-edge assistance for controlled comparison')
    p.add_argument('--no-lowtip-tracking',action='store_true',help='Compare with v6 segmentation and low-tip tracking rules')
    p.add_argument('--guided',action='store_true')
    p.add_argument('--automatic',action='store_true',help='Continuous dark-backdrop mode, no operator calibration')
    p.add_argument('--guide-frames',type=int,default=20)
    p.add_argument('--protocol-stdout',action='store_true',help='Strict bytes on current foreground login TTY, no second UART open')
    p.add_argument('--hdmi',action='store_true',help='Display real final_hand_mask; independent of diagnostic images')
    p.add_argument('--hdmi-hz',type=float,default=5.0,help='Display submission rate >0 and <=5; never limits capture')
    p.add_argument("--hand",action="store_true",help="Enable manually authorized direct endpoint follower")
    return p


def main(argv=None):
    p=parser(); args=p.parse_args(argv)
    if (args.frames<0 or args.save_every<1 or args.max_saved<0 or not 8<=args.max_mib<=2048 or
        not math.isfinite(args.image_interval) or not 0.2<=args.image_interval<=60 or
        not math.isfinite(args.capture_timeout) or not 0<args.capture_timeout<=10 or not 1<=args.guide_frames<=100):
        p.error('Invalid bounded time/count/capacity settings')
    if not math.isfinite(args.hdmi_hz) or not 0 < args.hdmi_hz <= 5:
        p.error('--hdmi-hz must be finite, >0 and <=5')
    if args.images and not args.replay_output: p.error('--images requires --replay-output')
    if args.hardware and args.replay_output: p.error('Hardware output must use verified SD mount')
    if args.guided and (not args.hardware or args.no_input): p.error('Guided acquisition requires live hardware and interactive input')
    if args.automatic and args.guided: p.error('--automatic and --guided are mutually exclusive')
    if args.hand and (not args.hardware or not args.automatic): p.error('Hand requires live automatic mode')
    source='LIVE' if args.hardware else 'REPLAY'
    hand=None; hand_captured=time.monotonic()
    display=None
    store=terminal=hw=saver=None; seq=0; count=0; error=None; rc=1
    epoch=time.monotonic(); previous=None; previous_driver_seq=None; last_status=None
    pending_empty=False; guide=Guide(args.guide_frames) if args.guided else None
    old_signals={}; last_guide_notice=0.0; edge_ready_prev=False
    def stop_signal(signum,frame): raise KeyboardInterrupt()
    def message(text):
        if store: store.event(text)
        if not args.protocol_stdout: print(text,flush=True)
    def emit(result, persist=True, to_hand=True):
        nonlocal seq
        packet=encode(seq,int((time.monotonic()-epoch)*1000),result,source); seq+=1
        if hand and to_hand: hand.submit(packet,hand_captured)
        if persist and store: store.packet(packet)
        decoded=decode(packet)
        if terminal and args.protocol_stdout: terminal.send(packet)
        elif not args.protocol_stdout:
            print('[G1] seq={0} {1} raw={2} code={3} valid={4} reason={5}'.format(
                decoded['seq'],decoded['status'],decoded['raw'],decoded['code'],int(decoded['valid']),result.get('raw',{}).get('reason','')),flush=True)
        return decoded
    try:
        cfg=load_config(args.config)
        cfg.gesture_confirm_frames=1; cfg.gesture_hold_frames=0; cfg.calibration_stable_frames=1
        cfg.validate()
        if (cfg.width,cfg.height)!=(320,240): raise ValueError('Algorithm input must remain 320x240')
        if args.hardware and (os.geteuid()!=0 or platform.release()!='4.19.0-xilinx-v2019.1'):
            raise RuntimeError('Live mode requires root on the verified 4.19.0-xilinx-v2019.1 board')
        if guide and guide.count<cfg.background_frames: raise ValueError('guide-frames must cover background_frames')
        interactive=not args.no_input and sys.stdin.isatty()
        if guide and not interactive: raise RuntimeError('Guided acquisition requires a foreground login terminal')
        terminal=ForegroundTerminal(args.protocol_stdout,interactive)
        for signum in (signal.SIGTERM,signal.SIGHUP):
            old_signals[signum]=signal.signal(signum,stop_signal)
        store=RunStore(args.mount if args.hardware else args.replay_output,args.hardware,
                       args.max_mib*1024*1024,args.max_saved)
        store.metadata('config.json',{'algorithm':asdict(cfg),'runtime':vars(args)})
        store.metadata('environment.json',{'python':sys.version,'machine':platform.machine(),'kernel':platform.release(),
            'numpy':np.__version__,'opencv':cv2.__version__,'scope':source,
            'physical_measurement':bool(args.hardware),'target_expected':'ARMv7 Python3.5.6 NumPy1.14.5 OpenCV3.4.3'})
        store.metadata('manifest.json',{'run':store.directory.name,'source':source,'orientation':args.orientation,
            'order':['Thumb','Index','Middle','Ring'],'five_fingers_required_for_calibration':True,
            'camera_table_sha256':hashlib.sha256(Path(args.camera_table).read_bytes()).hexdigest(),
            'algorithm_config_sha256':hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
            'frame_age_gate':False,'accuracy_not_measured':True})
        message('RUN_DIR '+str(store.directory))
        if args.hand:
            from hand_bridge import HandBridge
            message('HAND FINAL: any new complete LIVE raw triggers endpoints; 1=straight 0=bent; Q/Ctrl+C releases torque')
            hand=HandBridge(store.directory)
        if args.automatic:
            message('AUTO_CONTINUOUS: show all five fingers once, then move freely; no EMPTY/NEXT/K needed. Q stops.')
        elif guide:
            message('GUIDED: first EMPTY + Enter with no hand; then follow NEXT prompts. B restarts background; Q stops.')
        else:
            message('LIVE: B + Enter then EMPTY + Enter with no hand; K resets identity; Q stops.')
        if not args.automatic:
            message('LIVE OUTPUT REQUIRES CALIBRATED BACKGROUND; every accepted command prints INPUT_ACK.')
        else:
            message('AUTO_BLACK_BACKGROUND: dark matte backdrop required; stable open hand automatically reacquires identity.')
            message('EDGE_ASSIST '+('OFF' if args.no_edge_assist else 'ON: new interior edges assist only uncertain retracted fingers; identity reference still required.'))
            message('LOWTIP_TRACKING '+('OFF' if args.no_lowtip_tracking else 'ON'))
        message('SKIN_RANGE Cr={0}..{1} Cb={2}..{3}'.format(cfg.cr_min,cfg.cr_max,cfg.cb_min,cfg.cb_max))
        message('Open ALL FIVE fingers for identity calibration; output remains thumb/index/middle/ring only.')
        # Avoid OpenCV oversubscribing the dual-core CPU alongside the writer.
        cv2.setNumThreads(1)
        recognizer=HeadlessRecognizer(cfg,automatic=True,edge_assist=not args.no_edge_assist,lowtip_tracking=not args.no_lowtip_tracking) if args.automatic else HeadlessRecognizer(cfg)
        display=MaskDisplay(enabled=args.hdmi,hz=args.hdmi_hz)
        if not args.no_images:
            saver=AsyncImages(store,cfg,args.image_interval)
        # Camera initialization is not a captured frame; do not start the
        # LIVE-stream watchdog with this administrative startup message.
        emit(invalid('PENDING'),to_hand=False)
        if args.hardware:
            from hardware_vga import HardwareVGA
            # Driver open is exclusive. EBUSY is fatal; no second open, retries, or module reload.
            hw=HardwareVGA(args.device)
            hw.report_sensor_id=lambda chip: message('OV5640_ID 0x{0:04X}'.format(chip))
            message('GST2_ID 0x{0:08X}'.format(hw.read(0)))
            hw.initialize(args.camera_table)
            wanted=hw.camera_read(0x503d)&0x7f; hw.camera_write(0x503d,wanted)
            if hw.camera_read(0x503d)!=wanted or hw.camera_read(0x4740)!=0x20:
                raise RuntimeError('Live-mode sensor readback mismatch')
            message('INITIALIZED 0x4740=0x20 COLORBAR_OFF=1; settling 1 second')
            time.sleep(1)
        else:
            paths=iter(sorted(Path(args.images).glob(args.pattern)))
        if guide: message(guide.prompt())
        while not args.frames or count<args.frames:
            quit_requested=False
            for command in terminal.commands():
                if args.automatic and command != 'Q':
                    message('INPUT_IGNORED automatic mode needs no calibration commands; Q stops.')
                    continue
                pending_empty, quit_requested = operator_command(
                    command,guide,recognizer,pending_empty,message,emit)
                if quit_requested: break
            if quit_requested: break
            started=time.monotonic(); hand_captured=started; diag={}; input_path=None
            if hw:
                frame_id,full=hw.capture(args.capture_timeout); diag=hw.diagnostics(); validate_diag(diag,frame_id)
                if previous_driver_seq is not None and frame_id != ((previous_driver_seq+1)&0xffffffff):
                    raise RuntimeError('Non-consecutive hardware frame sequence')
                previous_driver_seq=frame_id
            else:
                path=next(paths,None)
                if path is None: break
                input_path=str(path); full=read_png(path); frame_id=count+1
            captured=time.monotonic()
            previous=captured
            frame=preprocess(full,args.orientation); preprocessed=time.monotonic()
            was_capturing=recognizer.background.samples is not None
            result,masks,timing=recognizer.process(frame)
            if display.enabled:
                display.submit(masks.get('final_hand_mask'))
            algorithm_result=result
            if args.automatic and not args.no_edge_assist:
                edge_ready=bool(result.get('raw',{}).get('edge_assistance',{}).get('baseline_ready'))
                if edge_ready != edge_ready_prev:
                    message('EDGE_BASELINE_READY' if edge_ready else 'EDGE_BASELINE_RELEARNING; geometric recognition remains active')
                    edge_ready_prev=edge_ready
            if was_capturing:
                result=invalid('CALIBRATING','explicit_empty_scene_capture')
                if recognizer.background.samples is None:
                    recognizer.reset('background_completed'); message('BACKGROUND_CAPTURE_COMPLETE; show ALL FIVE spread fingers')
            if args.hardware and not recognizer.background.last_info.get('effective') and not was_capturing:
                result=invalid('CALIBRATING','dark_backdrop_required' if args.automatic else 'empty_background_required')
            if pending_empty: result=invalid('CALIBRATING','awaiting_empty_scene_confirmation')
            saved={'saved':False,'reason':'performance_mode' if args.no_images else 'interval'}
            save_start=time.monotonic()
            label=guide.label() if guide else None
            # Only snapshot/enqueue here. Annotation, PNG encoding and fsync run
            # in the bounded worker. Queue pressure drops diagnostics, not frames.
            if saver and (count%args.save_every==0 or result['status']!=last_status or label is not None):
                saved=saver.submit(count+1,full,frame,masks,recognizer.last_palm,
                                   recognizer.last_features,algorithm_result,
                                   {'frame_id':int(frame_id),'operator_label':label,
                                    'algorithm_status':algorithm_result['status'],
                                    'final_protocol_in_frames_jsonl':True})
            save_end=time.monotonic()
            send_start=time.monotonic(); packet_record=emit(result); sent=time.monotonic()
            timing.update(capture_ms=(captured-started)*1000,preprocess_ms=(preprocessed-captured)*1000,
                          save_ms=(save_end-save_start)*1000,image_enqueue_ms=(save_end-save_start)*1000,encode_serial_ms=(time.monotonic()-send_start)*1000)
            row={'kind':'frame','frame_id':int(frame_id),'frame_index':count+1,'monotonic':captured,
                 'source':source,'input_path':input_path,'orientation':args.orientation,'driver':diag,
                 'result':result,'algorithm_result':algorithm_result,'protocol':packet_record,
                 'background':recognizer.background.last_info,'operator_label':label,'automatic_mode':args.automatic,
                 'timing_ms':timing,'images':saved}
            record_start=time.monotonic(); store.record(row)
            timing['record_io_ms']=(time.monotonic()-record_start)*1000
            timing['cycle_total_ms']=(time.monotonic()-started)*1000
            store.cycle(timing)
            store.record({'kind':'cycle_complete','frame_id':int(frame_id),'timing_ms':timing,
                          'excludes':'this small final timing-record serialization; includes preceding frame-record flush'})
            count+=1; last_status=result['status']
            if guide:
                ready=bool(recognizer.background.last_info.get('effective')) and not pending_empty
                confirmed=bool(packet_record['valid'] and packet_record['code']=='1111')
                if guide.advance(ready,confirmed):
                    message(guide.prompt())
                elif guide.waiting_reason and time.monotonic()-last_guide_notice>=5:
                    message('GUIDE_WAIT '+guide.waiting_reason+'; do not bend fingers yet; Q to stop.')
                    last_guide_notice=time.monotonic()
        if not count and not interactive: raise RuntimeError('No input frames processed')
        emit(invalid('STOPPED')); rc=0
    except KeyboardInterrupt:
        try: emit(invalid('STOPPED'))
        except Exception:
            try: emit(invalid('STOPPED'),persist=False)
            except Exception: pass
        rc=0
    except Exception as exc:
        error=str(exc)
        try: emit(invalid('CAPTURE_ERROR',error))
        except Exception:
            try: emit(invalid('CAPTURE_ERROR',error),persist=False)
            except Exception: pass
        if not args.protocol_stdout: print('ERROR: '+error,file=sys.stderr,flush=True)
        if store:
            try:
                store.event('ERROR '+error)
                diagnostics=None
                if hw:
                    try: diagnostics=hw.diagnostics()
                    except Exception: diagnostics={'readback_failed':True}
                store.record({'kind':'error','reason':error,'driver':diagnostics,
                              'last_completed_driver_sequence':previous_driver_seq,'source':source})
            except Exception: pass
        rc=1
    finally:
        if hand:
            hand_rc=hand.close()
            if not hand.release_verified:
                error="Actuator release unconfirmed; cut servo power and inspect hand logs"; rc=1
                print("HAND_RELEASE_NOT_CONFIRMED: CUT SERVO POWER",file=sys.stderr,flush=True)
            elif hand_rc:
                error="Actuator fault; torque-off verified; inspect hand logs"; rc=1
                print("HAND_FAULT_RELEASE_VERIFIED: stopped on fault; all eight torque-off verified",file=sys.stderr,flush=True)
        if hw:
            try: hw.close()
            except Exception as exc: error=str(exc); rc=1
        display_summary = None
        if display:
            try: display_summary=display.close()
            except Exception as exc:
                display_summary={'error':repr(exc),'shutdown_unconfirmed':True}
        image_summary = None
        if saver:
            image_summary = saver.close()
            if image_summary['error']:
                error = 'DIAGNOSTIC_IMAGES: '+image_summary['error']; rc=1
        if store:
            try:
                store.summary({'return_code':rc,'error':error,'source':source,'processed_frames':count,
                    'elapsed_seconds':time.monotonic()-epoch,'frame_age_gate':False,
                    'async_images':image_summary,'hdmi':display_summary,
                    'live_recognition_rate_not_inferred_from_replay':True})
            except Exception as exc:
                rc=1
                if not args.protocol_stdout: print('SUMMARY_WRITE_FAILED '+str(exc),file=sys.stderr)
            try: store.close()
            except Exception: rc=1
        if terminal:
            try: terminal.close()
            except Exception as exc: print('RESTORE_FAILED '+str(exc),file=sys.stderr); rc=1
        for signum,handler in old_signals.items(): signal.signal(signum,handler)
    return rc

if __name__=='__main__': sys.exit(main())
