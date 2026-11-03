from pathlib import Path
import numpy as np,cv2,shutil,hashlib,json
B=Path(__file__).resolve().parents[1]
src=Path('/home/huzhen/linux_stage2_20261030/input/samples/run-d5d7ca2a5b784049be1bf39a964ebed5')
paths=sorted(src.glob('real-*.png'));assert len(paths)==3
out=B/'evidence/replay-input';out.mkdir(exist_ok=True)
for p in paths:shutil.copyfile(str(p),str(out/p.name))
np.save(str(out/'replay.npy'),np.stack([cv2.imread(str(p)) for p in paths]))
(out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.name!='SHA256SUMS'))
