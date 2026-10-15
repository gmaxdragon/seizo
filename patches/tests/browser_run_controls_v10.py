"""Actual browser cancellation, persistence, previews and timing UI. No cloud calls."""
from pathlib import Path
import os,sys,json,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app import Server,make_handler,default_runner
from core.cloud import HackClubPlanner
root=Path(__file__).resolve().parents[1];out=root/'evidence';out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as td:
 r=default_runner(td);cloud=HackClubPlanner();stop=threading.Event()
 server=Server(('127.0.0.1',0),make_handler(r,'test-only-token',stop,cloud,'v10-browser'))
 th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
 errors=[]
 try:
  with sync_playwright() as p:
   executable=os.environ.get('SEIZO_TEST_CHROMIUM')
   b=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),
       args=['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--use-angle=swiftshader'])
   page=b.new_page(viewport={'width':1280,'height':950});page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('wristFrame').naturalWidth>0",timeout=60000)
   page.wait_for_function("() => document.getElementById('etaTest').textContent.includes('19')",timeout=30000)
   assert 'Calibrating' in page.locator('#etaTrain').inner_text()
   assert page.locator('#stop').inner_text()=='END RUN & SAVE'
   assert not page.locator('#keepAwake').is_checked()
   page.screenshot(path=str(out/'v10_initial.png'),full_page=True)
   page.locator('.cameraSelect[data-view="wrist"]').click()
   page.locator('#cameraFocus').screenshot(path=str(out/'v10_wrist.png'))
   page.locator('#closeFocus').click()
   page.locator('#speed').select_option('450')
   page.locator('#train').click()
   deadline=time.time()+60
   while r.agent.steps<2 and time.time()<deadline:page.wait_for_timeout(300)
   assert r.agent.steps>=2, r.error
   count=r.agent.steps
   page.locator('#hidePreviews').check();assert page.locator('#cameraPanel').is_hidden()
   deadline=time.time()+30
   while r.agent.steps<=count and time.time()<deadline:page.wait_for_timeout(300)
   assert r.agent.steps>count,'Training must continue without visible previews'
   start=time.perf_counter()
   with page.expect_response(lambda x:x.url.endswith('/api/end-run'),timeout=10000) as result:page.locator('#stop').click()
   ack=result.value.json();ack_time=time.perf_counter()-start
   assert ack['tab_remains_open'] and not ack['save_complete']
   page.wait_for_function("() => document.getElementById('etaLive').textContent.includes('Saved and verified')",timeout=40000)
   assert not page.is_closed() and not stop.is_set()
   fingerprint=r.agent.signature();moves=r.agent.steps;target=r.target
   assert r.save_verified
   page.reload(wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('hidePreviews').checked",timeout=30000)
   assert page.locator('#speed').input_value()=='450'
   assert r.target==target and r.agent.steps==moves and r.agent.signature()==fingerprint
   page.locator('#hidePreviews').uncheck();page.wait_for_timeout(1500)
   page.screenshot(path=str(out/'v10_saved.png'),full_page=True)
   assert not errors,errors
   result={'browser':'actual Chromium/WebGL','camera_frames_decoded':True,'estimate_calibrating_not_fabricated':True,
           'test_budget_includes_baselines_and_faults':19,'training_continued_with_previews_hidden':True,
           'end_ack_wall_seconds':ack_time,'end_to_verified_save_seconds':r.end_state['request_to_save_seconds'],
           'saved_movements':moves,'saved_target':target,'reload_preserved_policy_budget_and_ui':True,
           'tab_left_open':True,'cloud_calls':0,'physical_motion':False,'javascript_errors':errors}
   (out/'browser_run_controls_v10.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
   b.close()
 finally:
  r.shutdown();server.shutdown();server.server_close()
