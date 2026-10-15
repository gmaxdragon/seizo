#!/usr/bin/env python3
"""Laptop-only Seizo neural learning lab. No physical controller backend."""
from __future__ import annotations
import os
# Avoid BLAS oversubscription competing with CAD on a modest laptop.
for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[_key]='1'
import argparse,http.server,json,secrets,signal,sys,threading,urllib.parse,webbrowser
import time,uuid
from core.startup import wait_ready, write_instance, existing_url, clear_instance
from pathlib import Path
from core.runner import Runner,World
from core.cloud import HackClubPlanner

ROOT=Path(__file__).resolve().parent
BUILD='seizo-run-controls-v10';PORT=8772

class DataLock:
    def __init__(self,path):
        Path(path).mkdir(parents=True,exist_ok=True)
        self.f=open(Path(path)/'.instance.lock','a+b');self.f.seek(0,2)
        if self.f.tell()==0:self.f.write(b'0');self.f.flush()
        self.f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.f.close();raise RuntimeError('This folder is already open. Close its previous Seizo terminal, or use its existing browser page.')
    def close(self):self.f.close()

class Server(http.server.ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True


def make_handler(runner,token,quit_event,cloud,instance_id='test-instance'):
    key_commands=threading.Lock();key_state={'seq':-1}
    command_lock=threading.Lock();command_state={'seq':-1}
    def strict_json(raw):
        def bad_number(value):raise ValueError('Non-finite JSON number')
        return json.loads(raw,parse_constant=bad_number)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass # Never log credentials or POST bodies.
        def send(self,code,data,kind='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data,allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
        def local(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        def expected_origin(self):return 'http://'+self.headers.get('Host','')
        def auth(self):return secrets.compare_digest(self.headers.get('X-Lab-Token',''),token)
        def do_GET(self):
            if not self.local():return self.send(403,{'error':'Invalid host. Open the exact address printed in the terminal.'})
            path=urllib.parse.urlsplit(self.path).path
            if path=='/healthz':
                return self.send(200,{'app':'SeizoLearn','ready':True,'build':BUILD,'instance':instance_id})
            if path=='/':
                html=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('__TOKEN__',token)
                return self.send(200,html.encode(),'text/html; charset=utf-8')
            if path.startswith('/api/'):
                if not self.auth():return self.send(403,{'error':'Reopen the home page to restore this session.'})
                if path=='/api/status':return self.send(200,{**runner.snapshot(),'build':BUILD,'cloud':cloud.status()})
                if path=='/api/experience':return self.send(200,runner.experience_summary())
                if path=='/api/initial':
                    if runner.is_camera:
                        try:return self.send(200,runner.camera_preview())
                        except (ValueError,RuntimeError) as e:
                            return self.send(503,{'error':str(e)[:500]})
                    return self.send(200,World(1,seed=61).frame())
                if path=='/api/hackclub/status':return self.send(200,cloud.status())
                return self.send(404,{'error':'No such endpoint. There is no motor or camera control route.'})
            name=urllib.parse.unquote(path).lstrip('/')
            asset=(ROOT/'web'/name).resolve();web=(ROOT/'web').resolve()
            types={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json'}
            if asset.is_relative_to(web) and asset.is_file() and asset.suffix in types:
                return self.send(200,asset.read_bytes(),types[asset.suffix])
            return self.send(404,{'error':'File not found.'})
        def do_POST(self):
            if not self.local() or not self.auth() or self.headers.get('Origin')!=self.expected_origin():
                return self.send(403,{'error':'Only this local Seizo page can send commands.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'JSON required.'})
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=16000:raise ValueError('Invalid request size.')
                self.connection.settimeout(5.)
                data=strict_json(self.rfile.read(n))
                if not isinstance(data,dict):raise ValueError('Expected a JSON object.')
                path=urllib.parse.urlsplit(self.path).path
                if path in ('/api/start','/api/trial','/api/evaluate','/api/gripper-check') and World.__module__!='core.mujoco_world':
                    raise ValueError('MuJoCo is unavailable. Close Seizo and reopen START_SEIZO.bat to repair dependencies. Training is blocked instead of using the old contact model.')
                def keys(allowed):
                    if set(data)-set(allowed):raise ValueError('Unknown setting.')
                if path in ('/api/start','/api/stop','/api/end-run'):
                    seq=data.pop('control_seq',None)
                    if type(seq)is not int or not 0<=seq<2**53:raise ValueError('Invalid command sequence. Refresh the page.')
                    with command_lock:
                        if seq<=command_state['seq']:raise ValueError('A newer command or STOP replaced this request.')
                        command_state['seq']=seq
                        if path=='/api/start':result=runner.start(data)
                        elif path=='/api/end-run':
                            keys(('settings',));result=runner.end_run(data.get('settings'))
                        else:
                            keys(());result=runner.stop()
                elif path=='/api/estimate':
                    keys(('kind','episodes','task','trials','compute'));result=runner.estimate_run(**data)
                elif path=='/api/session-settings':
                    keys(('settings',));result=runner.set_session(data.get('settings',{}))
                elif path=='/api/trial':
                    keys(('task','source','fault','seed'))
                    if type(data.get('fault',False))is not bool:raise ValueError('Invalid fault setting.')
                    result=runner.trial(**data)
                elif path=='/api/gripper-check':
                    keys(('mode',))
                    with runner.lock:
                        if runner.status in ('training','stopping','evaluating','watching'):
                            raise ValueError('Stop and save before checking the gripper.')
                    from core.gripper_check import run_check
                    result=run_check(data.get('mode','open_close'))
                elif path=='/api/evaluate':
                    keys(('task','trials'));result=runner.begin_evaluation(data.get('task','all'),data.get('trials',20))
                elif path=='/api/views/config':
                    keys(('mode',));result=runner.set_views(data.get('mode','auto'))
                elif path=='/api/cameras/config':
                    keys(('profile','overhead_height_m','overhead_side_m','wrist_mount','frame_faults','framing','wrist_height_m'))
                    result=runner.set_cameras(data)
                elif path=='/api/cameras/preview':
                    keys(());result=runner.camera_preview(resample=True)
                elif path=='/api/reset':
                    keys(('confirmed',))
                    if data.get('confirmed') is not True:raise ValueError('Confirm backup and reset first.')
                    result=runner.reset()
                elif path in ('/api/hackclub/key','/api/hackclub/forget'):
                    # Serialize mutations, reject stale automatic-save requests after Delete.
                    seq=data.pop('key_seq',None)
                    if seq is not None and (type(seq)is not int or not 0<=seq<2**53):raise ValueError('Invalid key action sequence.')
                    with key_commands:
                        if seq is not None and seq<=key_state['seq']:raise ValueError('A newer key action replaced this request.')
                        if seq is not None:key_state['seq']=seq
                        if path=='/api/hackclub/key':keys(('key',));result=cloud.set_key(data.get('key',''))
                        else:keys(());result=cloud.clear_key()
                elif path=='/api/hackclub/reveal':
                    keys(('confirmed',))
                    if data.get('confirmed')is not True:raise ValueError('Click Show to reveal your saved key on this screen.')
                    result=cloud.reveal_key()
                elif path=='/api/hackclub/test':keys(('model',));result=cloud.test_connection(data.get('model','qwen/qwen3-32b'))
                elif path=='/api/hackclub/review':
                    keys(('model',));result=cloud.review_results(runner.experience_summary(),data.get('model','qwen/qwen3-32b'))
                elif path=='/api/quit':keys(());runner.stop();quit_event.set();result={'ok':True}
                else:return self.send(404,{'error':'No such endpoint. No hardware-control backend exists.'})
                return self.send(200,result)
            except (ValueError,TypeError,KeyError,OSError,RuntimeError) as e:return self.send(400,{'error':str(e)})
            except Exception:return self.send(500,{'error':'Unexpected local error. Stop and restart; your saved policy is retained.'})
    return Handler


def default_runner(data_dir):
    """Production uses ONLY fake-camera observations; no opt-in or truth fallback."""
    from core.session_runner import SessionRunner
    return SessionRunner(Path(data_dir)/'camera_views_v9')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=PORT)
    p.add_argument('--data-dir',type=Path,default=ROOT/'data')
    p.add_argument('--no-browser',action='store_true')
    a=p.parse_args()
    if not 0<=a.port<=65535:raise ValueError('Invalid local port.')
    a.data_dir=a.data_dir.resolve()
    try:
        lock=DataLock(a.data_dir)
    except RuntimeError:
        url=existing_url(a.data_dir,BUILD)
        if url:
            print('Seizo is already running. Reopening that page: '+url,flush=True)
            if not a.no_browser:webbrowser.open(url)
            return
        raise
    runner=None;server=None;worker=None;instance=uuid.uuid4().hex
    quit_event=threading.Event()
    try:
        # Existing state policies and shared credentials remain untouched.
        runner=default_runner(a.data_dir)
        print('Input mode: DETAILED SIMULATED VIEWS. Helper views during exploration; all scored tests use wrist + overhead only.',flush=True)
        cloud=HackClubPlanner(audit_path=a.data_dir/'api_usage.json');token=secrets.token_urlsafe(32)
        try:
            if os.name=='nt':
                import ctypes
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.GetCurrentProcess.restype=ctypes.c_void_p
                kernel.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
                kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x4000)
            else:os.nice(5)
        except Exception:pass
        handler=make_handler(runner,token,quit_event,cloud,instance)
        try:server=Server(('127.0.0.1',a.port),handler)
        except OSError:
            server=Server(('127.0.0.1',0),handler)
            print('The usual port is busy. Using a free local port instead.',flush=True)
        server.timeout=.25
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True)
        worker.start()
        if not wait_ready(server.server_port,instance):
            raise RuntimeError('Local readiness check failed. Browser was not opened. See logs/startup.log.')
        write_instance(a.data_dir,server.server_port,instance,BUILD)
        url=f'http://127.0.0.1:{server.server_port}/?build={BUILD}'
        for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *args:quit_event.set())
        print('\nSEIZO READY: '+url,flush=True)
        print('Local server responded successfully before opening your browser.',flush=True)
        print('Keep this terminal open. The API-key controls are on the main page.',flush=True)
        print('Training is LOCAL and does not need an API key. No physical robot connection.\n',flush=True)
        if not a.no_browser:
            try:
                if not webbrowser.open(url):print('Open the exact READY address above in your browser.',flush=True)
            except Exception:print('Open the exact READY address above in your browser.',flush=True)
        while not quit_event.wait(.25):pass
    finally:
        try:
            if runner:runner.shutdown()
        finally:
            if server:
                if worker:server.shutdown()
                server.server_close()
            if worker:worker.join(timeout=3)
            clear_instance(a.data_dir,instance)
            lock.close()
        print('Saved. You can close this terminal.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('\nCould not start safely: '+str(e),file=sys.stderr)
        print('No API key was logged. Run START.bat again; if it fails, open logs/startup.log.',file=sys.stderr)
        sys.exit(1)
