import contextlib,io,json,os,select,shlex,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest import mock
B=Path(__file__).resolve().parents[1];D=B/'delivery';sys.path.insert(0,str(D))
import start_follow,verify_files

class ReleaseTests(unittest.TestCase):
 def test_manifest_complete(self):self.assertGreater(verify_files.verify(),40)
 def test_shell_scripts_are_lf_without_bom(self):
  for p in D.rglob('*.sh'):
   data=p.read_bytes();self.assertTrue(data.startswith(b'#!/bin/sh\n'));self.assertNotIn(b'\r',data)
 def test_wrong_confirmation_never_executes(self):
  with mock.patch.object(sys,'argv',['start_follow.py']),mock.patch.object(start_follow,'confirm_interactive',return_value='FOLLOW5'),mock.patch.object(os,'execv') as execute:
   self.assertEqual(start_follow.main(),1);execute.assert_not_called()
 def test_confirm_test_never_executes(self):
  with mock.patch.object(sys,'argv',['start_follow.py','--confirm-test']),mock.patch.object(start_follow,'confirm_interactive',return_value='FOLLOW_FINAL'),mock.patch.object(os,'execv') as execute:
   self.assertEqual(start_follow.main(),0);execute.assert_not_called()
 def test_extra_motion_arguments_refused(self):
  with mock.patch.object(sys,'argv',['start_follow.py','--full-range']),mock.patch.object(os,'execv') as execute:
   with self.assertRaises(RuntimeError):start_follow.main()
   execute.assert_not_called()
 def test_authorized_exec_has_fixed_final_launch(self):
  with mock.patch.dict(os.environ,{},clear=False),mock.patch.object(sys,'argv',['start_follow.py']),mock.patch.object(start_follow,'confirm_interactive',return_value='FOLLOW_FINAL'),mock.patch.object(os,'execv') as execute:
   start_follow.main();self.assertEqual(os.environ['GESTURE_HAND_FINAL_ACK'],'FOLLOW_FINAL')
   args=execute.call_args[0][1];self.assertIn('--automatic',args);self.assertIn('--hand',args);self.assertIn('--hardware',args)
 def test_changed_missing_extra_files_refused(self):
  for mode in ('changed','missing','extra'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'release';shutil.copytree(str(D),str(root))
    if mode=='changed':(root/'app/ps/hand_final.py').write_bytes(b'changed')
    elif mode=='missing':(root/'run_follow.sh').unlink()
    else:(root/'unexpected.py').write_bytes(b'')
    with mock.patch.object(verify_files,'__file__',str(root/'verify_files.py')):
     with self.assertRaises(RuntimeError):verify_files.verify()

@unittest.skipUnless(os.name=='posix','Actual shell/TTY tested on Linux')
class TTYTests(unittest.TestCase):
 def run_tty(self,token):
  master,slave=os.openpty();out=b''
  with tempfile.TemporaryDirectory() as tmp:
   exe=json.loads(os.environ.get('DIAG_TEST_PYTHON',json.dumps([sys.executable])))
   shim=Path(tmp)/'python3';shim.write_bytes(('#!/bin/sh\nexec '+' '.join(shlex.quote(x) for x in exe)+' "$@"\n').encode());shim.chmod(0o700)
   env=dict(os.environ);env['PATH']=tmp+':'+env['PATH'];env['PYTHONDONTWRITEBYTECODE']='1'
   child=subprocess.Popen(['sh',str(D/'confirm_input.sh')],stdin=slave,stdout=slave,stderr=slave,env=env)
   try:
    deadline=time.monotonic()+15
    while b'Type FOLLOW_FINAL' not in out and time.monotonic()<deadline:
     if select.select([master],[],[],.1)[0]:out+=os.read(master,8192)
    self.assertIn(b'Type FOLLOW_FINAL',out)
    os.write(master,b'\n');time.sleep(.12);self.assertIsNone(child.poll())
    os.write(master,token.encode()+b'\n')
    child.wait(timeout=15)
    while select.select([master],[],[],.1)[0]:out+=os.read(master,8192)
    return child.returncode,out
   finally:
    if child.poll() is None:child.kill();child.wait()
    os.close(master);os.close(slave)
 def test_actual_shell_waits_after_blank_and_accepts_follow_final(self):
  rc,out=self.run_tty('FOLLOW_FINAL');self.assertEqual(rc,0,out);self.assertIn(b'"servo_uart_opened": false',out)
 def test_actual_shell_rejects_follow5(self):
  rc,out=self.run_tty('FOLLOW5');self.assertNotEqual(rc,0);self.assertIn(b'CANCELLED_NO_WRITES',out)
 def test_pipe_is_not_authorization(self):
  exe=json.loads(os.environ.get('DIAG_TEST_PYTHON',json.dumps([sys.executable])))
  child=subprocess.Popen(exe+['-B',str(D/'start_follow.py'),'--confirm-test'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  out,err=child.communicate(b'FOLLOW_FINAL\n',timeout=15)
  self.assertNotEqual(child.returncode,0);self.assertIn(b'Interactive terminal required',err)

if __name__=='__main__':unittest.main(verbosity=2)
