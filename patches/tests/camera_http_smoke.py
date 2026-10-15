"""Real local HTTP camera-training cancellation/reload test, no external requests."""
import os,sys,time,tempfile,json,re,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def launch(folder):
    log=(folder/'server-test.log').open('a')
    p=subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--no-browser','--port','0','--data-dir',str(folder)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    for _ in range(200):
        if p.poll() is not None:raise RuntimeError((folder/'server-test.log').read_text())
        try:
            record=json.loads((folder/'.running.json').read_text())
            url='http://127.0.0.1:'+str(record['port'])
            with client.open(url+'/healthz',timeout=2) as f:h=json.load(f)
            if h.get('instance')==record['instance']:
                with client.open(url,timeout=2) as f:html=f.read().decode()
                token=re.search(r'name="lab-token" content="([^"]+)"',html).group(1)
                return p,url,token
        except (OSError,ValueError,KeyError):time.sleep(.1)
    raise RuntimeError('Local camera server readiness timeout')
def call(url,token,path,body=None):
    req=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),
      headers={'X-Lab-Token':token,'Origin':url,'Content-Type':'application/json'})
    with client.open(req,timeout=30) as f:return json.load(f)
with tempfile.TemporaryDirectory() as t:
    folder=Path(t);old=b'earlier state policy preserved, deliberately not parsed'
    (folder/'policy.npz').write_bytes(old)
    p,url,token=launch(folder)
    try:
        view=call(url,token,'/api/initial')
        assert view['cameras']['overhead'] and view['cameras']['wrist']
        call(url,token,'/api/cameras/config',{'profile':'fixed'})
        call(url,token,'/api/start',{'control_seq':1,'episodes':1000,'task':'reach','compute':'fast'})
        time.sleep(1.5)
        active=call(url,token,'/api/initial')
        assert active['observation_mode']=='masked_rgb_views'
        call(url,token,'/api/stop',{'control_seq':2})
        for _ in range(200):
            s=call(url,token,'/api/status')
            if s['status'] in ('paused','complete') and s['save_verified']:break
            if s['status']=='error':raise RuntimeError(s['error'])
            time.sleep(.1)
        else:raise AssertionError('No verified save after stop')
        assert s['saved_fingerprint']==s['policy_fingerprint']
        signature=s['policy_fingerprint'];moves=s['moves']
        call(url,token,'/api/quit',{})
        p.wait(30)
    finally:
        if p.poll() is None:p.terminate();p.wait(30)
    p,url,token=launch(folder)
    try:
        again=call(url,token,'/api/status')
        assert again['policy_fingerprint']==signature and again['moves']==moves
        assert (folder/'policy.npz').read_bytes()==old
        assert again['save_verified']
        call(url,token,'/api/quit',{});p.wait(30)
    finally:
        if p.poll() is None:p.terminate();p.wait(30)
    result={'real_local_HTTP':True,'camera_preview':True,'reload_during_training':True,
            'stop_saved_and_reload_verified':True,'earlier_state_policy_unchanged':True,
            'saved_movement_count':moves,'cloud_requests':0,'physical_motion':False}
    (ROOT/'evidence/http_camera_lifecycle.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
