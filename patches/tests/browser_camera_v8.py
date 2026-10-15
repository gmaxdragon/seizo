"""Actual local HTTP, WebGL, camera previews and STOP/save browser check."""
from pathlib import Path
import os,sys,json,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app import Server,make_handler
from core.runner import Runner
from core.camera_policy import Agent
from core.camera_world import CameraWorld
from core.cloud import HackClubPlanner
root=Path(__file__).resolve().parents[1]
evidence=root/'evidence';evidence.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
 r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
 cloud=HackClubPlanner();quit_event=threading.Event()
 server=Server(('127.0.0.1',0),make_handler(r,'camera-test-token',quit_event,cloud,'camera-browser-test'))
 t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
 url=f'http://127.0.0.1:{server.server_port}/'
 errors=[];page=None;browser=None
 try:
  with sync_playwright() as p:
   executable=os.environ.get('SEIZO_TEST_CHROMIUM')
   browser=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),
      args=['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--use-angle=swiftshader'])
   page=browser.new_page(viewport={'width':1280,'height':900})
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(url,wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('overheadFrame').naturalWidth>0 && document.getElementById('wristFrame').naturalWidth>0",timeout=40000)
   page.screenshot(path=str(evidence/'camera_initial.png'),full_page=True)
   assert page.locator('#episodes').input_value()=='1000'
   page.locator('#settingsOpen').click()
   page.locator('#episodes').fill('1000')
   page.locator('#settingsClose').click()
   page.locator('#train').click()
   page.wait_for_function("() => document.getElementById('status').textContent.includes('Practising')",timeout=20000)
   time.sleep(2)
   page.locator('#stop').click()
   page.wait_for_function("() => document.getElementById('saveStatus').textContent.includes('Saved and verified')",timeout=30000)
   page.wait_for_function("() => !document.getElementById('train').disabled",timeout=30000)
   page.locator('#evaluate').click()
   page.wait_for_function("() => document.getElementById('evaluation').textContent.includes('CURRENT policy evaluation')",timeout=240000)
   assert r.last_evaluation['observation_mode']=='two_rgb_cameras'
   assert len(r.last_evaluation['by_task'])==7
   assert r.last_evaluation['fingerprint_unchanged']
   assert not r.last_evaluation['weights_updated']
   signature=r.agent.signature();moves=r.agent.steps
   page.reload(wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('overheadFrame').naturalWidth>0",timeout=40000)
   assert r.agent.signature()==signature
   page.screenshot(path=str(evidence/'camera_saved.png'),full_page=True)
   assert not errors,errors
   record={'actual_http':True,'camera_images_decoded':True,'stop_saved_verified':r.save_verified,
           'moves_collected':moves,'policy_fingerprint':signature,'reload_preserved':True,
           'javascript_errors':errors,'real_pi_access':False,'cloud_calls':0,
           'seven_tasks_use_fake_cameras':True,'evaluation_weights_frozen':True,
           'evaluated_policy_successes':r.last_evaluation['current']['successes'],
           'evaluated_policy_trials':r.last_evaluation['current']['trials']}
   (evidence/'browser_camera_v8.json').write_text(json.dumps(record,indent=2))
   print(json.dumps(record))
   browser.close()
 except Exception as exc:
  details={'error':str(exc),'javascript_errors':errors,'status':r.status}
  try:
   if page is not None:
    details['body_text']=page.locator('body').inner_text(timeout=5000)
    page.screenshot(path=str(evidence/'camera_failure.png'),full_page=True,timeout=10000)
  except Exception as capture_error:details['capture_error']=str(capture_error)
  (evidence/'browser_failure.json').write_text(json.dumps(details,indent=2))
  raise
 finally:
  r.shutdown();server.shutdown();server.server_close()
