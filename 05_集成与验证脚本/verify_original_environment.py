from pathlib import Path
import hashlib,json
B=Path('/home/huzhen/hdmi_linux_integration_20261102')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pairs=[(Path('/home/huzhen/zynq_projects/zynq_ov5640/project-spec'),B/'backup/project-spec'),(Path('/home/huzhen/uart1_hand_20261101/build/boot'),B/'backup/uart1_boot')]
results=[]
for actual,backup in pairs:
 diffs=[];count=0
 for f in backup.rglob('*'):
  if not f.is_file():continue
  target=actual/f.relative_to(backup);count+=1
  if not target.is_file() or sha(f)!=sha(target):diffs.append(str(f.relative_to(backup)))
 results.append(dict(actual=str(actual),checked=count,changed=diffs));assert not diffs
kernel=Path('/home/huzhen/linux_stage1_20261030/build/kernel-obj')
assert sha(kernel/'.config')==sha(B/'backup/kernel.config')
assert sha(kernel/'Module.symvers')==sha(B/'backup/Module.symvers')
(B/'evidence/original_environment_preserved.json').write_text(json.dumps(dict(all_passed=True,trees=results,kernel_config_and_symbols_unchanged=True),indent=2))
print(results)
