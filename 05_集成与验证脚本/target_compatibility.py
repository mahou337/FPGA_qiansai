from pathlib import Path
import sys,json,platform
import numpy as np,cv2
B=Path(__file__).resolve().parents[1]
files=list((B/'delivery').rglob('*.py'))+list((B/'ps_display').glob('*.py'))+[B/'handoff_original/scripts/check_edid.py']
for p in files:compile(p.read_bytes(),str(p),'exec')
report=dict(python=sys.version,numpy=np.__version__,opencv=cv2.__version__,machine=platform.machine(),compiled_files=len(files),all_passed=True,scope='QEMU ARM user-mode; not board Linux driver or scanout')
(B/'evidence/target_compatibility.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
