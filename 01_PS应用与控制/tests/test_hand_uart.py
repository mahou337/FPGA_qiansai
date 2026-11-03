"""Offline POSIX pseudo-UART and simulated-bus watchdog tests. No physical ports."""
import json,os,sys,time,threading,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'delivery/app/ps'))
from hand_bus import SerialBus,IDS,packet
from protocol import encode
import hand_worker

class PseudoUARTTests(unittest.TestCase):
    def test_init_configures_1mbps_and_exclusive_lock(self):
        import termios,platform
        master,slave=os.openpty();device=os.ttyname(slave)
        self.addCleanup(os.close,master);self.addCleanup(os.close,slave)
        real_open=os.open
        with tempfile.TemporaryDirectory() as name:
            lockfile=str(Path(name)/'uart.lock')
            def opened(path,*args):
                return real_open(lockfile if path=='/run/gesture-hand-uart1.lock' else path,*args)
            with mock.patch('hand_bus.verify_uart_identity',return_value={'simulation':True}),mock.patch.object(platform,'machine',return_value='armv7l'),mock.patch.object(platform,'release',return_value='4.19.0-xilinx-v2019.1'),mock.patch.object(os,'geteuid',return_value=0),mock.patch.object(os,'open',side_effect=opened):
                try:bus=SerialBus(device)
                except RuntimeError as exc:
                    if os.environ.get('HAND_TEST_QEMU')=='1' and str(exc).startswith('Baud readback mismatch'):
                        self.skipTest('QEMU high-baud termios translation missing; native Linux test required')
                    raise
                try:
                    attrs=termios.tcgetattr(bus.fd)
                    self.assertEqual(attrs[4:6],[termios.B1000000,termios.B1000000])
                    self.assertEqual(attrs[2] & (termios.PARENB|termios.CSTOPB|getattr(termios,'CRTSCTS',0)),0)
                    with self.assertRaises(OSError):SerialBus(device)
                finally:bus.close()
    def transact(self,mode):
        import termios,select
        master,slave=os.openpty()
        attrs=termios.tcgetattr(slave);attrs[0]=attrs[1]=attrs[3]=0
        attrs[2]=termios.CS8|termios.CREAD|termios.CLOCAL
        attrs[6][termios.VMIN]=1;attrs[6][termios.VTIME]=0
        termios.tcsetattr(slave,termios.TCSANOW,attrs)
        bus=SerialBus.__new__(SerialBus);bus.fd=slave;bus.lock=None;bus.timeout=.3
        seen=[]
        def servo():
            buf=b''
            end=time.monotonic()+2
            while time.monotonic()<end:
                if select.select([master],[],[],.1)[0]:buf+=os.read(master,256)
                if len(buf)>=4 and len(buf)>=buf[3]+4:break
            seen.append(buf)
            data=b'\x01\xff' if mode!='short' else b'\x01'
            response=packet(2 if mode=='wrong_id' else 1,0,data)
            if mode=='bad_crc':response=response[:-1]+bytes(bytearray([response[-1]^1]))
            if mode!='timeout':os.write(master,response)
        thread=threading.Thread(target=servo);thread.start()
        try:
            if mode=='ok':self.assertEqual(bus.read(1,56,2),b'\x01\xff')
            else:
                with self.assertRaises(RuntimeError):bus.read(1,56,2)
            self.assertEqual(seen[0],packet(1,2,b'\x38\x02'))
        finally:thread.join(3);bus.close();os.close(master)
    def test_ok(self):self.transact('ok')
    def test_bad_crc(self):self.transact('bad_crc')
    def test_wrong_id(self):self.transact('wrong_id')
    def test_wrong_length(self):self.transact('short')
    def test_timeout(self):self.transact('timeout')

if __name__=='__main__':unittest.main(verbosity=2)
