"""Desktop-only baseline review; never drives hardware or asserts accuracy."""
import argparse
import json
import sys
from pathlib import Path
import cv2
import numpy as np

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--samples", required=True)
    p.add_argument("--output", required=True)
    a=p.parse_args()
    root=Path(a.workspace).resolve()
    samples=Path(a.samples).resolve()
    out=Path(a.output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root/"zynq_gesture"/"ps"))
    from headless import HeadlessRecognizer, load_config
    config=load_config(root/"zynq_gesture"/"config"/"algorithm.json")
    records=[]
    montage=[]
    for orientation in (0,180):
        recognizer=HeadlessRecognizer(config)
        for path in sorted(samples.glob("real-*.png")):
            raw=cv2.imread(str(path))
            if raw is None: raise RuntimeError(str(path))
            image=raw if orientation==0 else cv2.flip(raw,-1)
            frame=cv2.resize(image,(320,240),interpolation=cv2.INTER_AREA)
            result,masks,timing=recognizer.process(frame)
            key=path.stem+"_rot"+str(orientation)
            cv2.imwrite(str(out/(key+"_input.png")),frame)
            for name in ("skin_mask","clean_mask","final_hand_mask"):
                cv2.imwrite(str(out/(key+"_"+name+".png")),masks[name])
            record={"file":path.name,"orientation_degrees":orientation,
                    "status":result["status"],"code":result["code"],
                    "raw_code":result.get("raw",{}).get("code"),
                    "reason":result.get("raw",{}).get("reason"),
                    "skin_fraction":float(np.count_nonzero(masks["skin_mask"])/masks["skin_mask"].size),
                    "final_fraction":float(np.count_nonzero(masks["final_hand_mask"])/masks["final_hand_mask"].size),
                    "timing_desktop_ms":timing,"result":result}
            records.append(record)
            row=np.hstack([frame,cv2.cvtColor(masks["skin_mask"],cv2.COLOR_GRAY2BGR),cv2.cvtColor(masks["final_hand_mask"],cv2.COLOR_GRAY2BGR)])
            banner=np.zeros((32,row.shape[1],3),np.uint8)
            cv2.putText(banner,key+" | "+result["status"]+" | "+result["code"],(8,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
            montage.append(np.vstack([banner,row]))
    cv2.imwrite(str(out/"sample_review_montage.jpg"),np.vstack(montage))
    report={"python":sys.version,"opencv":cv2.__version__,"numpy":np.__version__,
            "scope":"Desktop baseline only; three near-identical open-hand images, no empty background; no accuracy or live-rate claim.",
            "config":"zynq_gesture/config/algorithm.json", "background_calibration":False,
            "frames":records}
    def convert(value):
        if isinstance(value,np.ndarray): return value.tolist()
        if isinstance(value,np.generic): return value.item()
        raise TypeError(type(value).__name__)
    (out/"baseline_replay.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=convert),encoding="utf-8")
    for r in records:
        print(r["file"],r["orientation_degrees"],r["status"],r["code"],r["raw_code"],r["reason"],round(r["skin_fraction"],4))

if __name__=="__main__": main()
