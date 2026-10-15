"""Actual UI clicks and rendering. No mocked API, movement or learning response."""
import os,sys,tempfile,time,threading,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app import default_runner,Server,make_handler
from core.cloud import HackClubPlanner
root=Path(__file__).resolve().parents[1];e=root/'evidence';e.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as td:
 r=default_runner(td);cloud=HackClubPlanner();srv=Server(('127.0.0.1',0),make_handler(r,'test-only',threading.Event(),cloud));threading.Thread(target=srv.serve_forever,daemon=True).start()
 errors=[]
 try:
  with sync_playwright() as p:
   executable=os.environ.get('SEIZO_TEST_CHROMIUM')
   browser=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),args=['--no-sandbox','--enable-unsafe-swiftshader','--use-angle=swiftshader','--disable-dev-shm-usage'])
   page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda er:errors.append(str(er)))
   page.goto(f'http://127.0.0.1:{srv.server_port}',wait_until='domcontentloaded')
   page.wait_for_function("() => ['overhead','wrist','side','front'].every(n=>document.getElementById(n+'Frame').naturalWidth===384)",timeout=60000)
   page.screenshot(path=str(e/'views_initial.png'),full_page=True)
   page.locator('[data-view=wrist]').click();page.locator('#cameraFocus').screenshot(path=str(e/'wrist_focus.png'))
   assert page.locator('#cameraFocus').is_visible();page.locator('#closeFocus').click()
   page.locator('#viewMode').select_option('two');page.locator('#saveViews').click()
   page.wait_for_function("() => document.querySelector('[data-view=side]').classList.contains('masked')",timeout=45000)
   assert r.agent.view_mode=='two'
   page.locator('#viewMode').select_option('auto');page.locator('#saveViews').click()
   page.wait_for_function("() => !document.querySelector('[data-view=side]').classList.contains('masked')",timeout=45000)
   sig=r.agent.signature();page.locator('#train').click()
   page.wait_for_function("() => document.getElementById('status').textContent.includes('Practising')",timeout=15000)
   deadline=time.time()+30
   while r.agent.steps<3 and time.time()<deadline:page.wait_for_timeout(300)
   page.locator('#stop').click()
   page.wait_for_function("() => document.getElementById('saveStatus').textContent.includes('Saved and verified') && !document.getElementById('train').disabled",timeout=45000)
   assert r.save_verified
   # Exercise a real Test-all invocation, then cancel. Never call that a pass.
   page.locator('#evaluate').click();page.wait_for_function("() => document.getElementById('status').textContent.includes('Frozen evaluation')",timeout=15000)
   page.wait_for_timeout(1800);page.locator('#stop').click()
   page.wait_for_function("() => document.getElementById('saveStatus').textContent.includes('Saved and verified') && !document.getElementById('train').disabled",timeout=45000)
   assert r.last_evaluation is None
   assert r.evaluation_options()['view_mode']=='two'
   last=r.agent.signature();page.reload(wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('overheadFrame').naturalWidth===384",timeout=45000)
   assert r.agent.signature()==last
   assert not errors,errors
   page.screenshot(path=str(e/'views_saved.png'),full_page=True)
   record={'actual_HTTP_and_WebGL':True,'all_four_rendered':True,'camera_focus_click':True,'two_only_masks_helpers':True,
     'train_stop_save_and_reload':True,'all_task_evaluation_started_and_cancelled':True,'cancel_not_a_pass':True,
     'evaluation_has_no_helper_views':True,'movement_decisions':r.agent.steps,'neural_updates':r.agent.updates,
     'javascript_errors':errors,'physical_motion':False,'full_task_skill_evaluation_claimed':False}
   (e/'browser_views_v9.json').write_text(json.dumps(record,indent=2));print(json.dumps(record));browser.close()
 finally:r.shutdown();srv.shutdown();srv.server_close()
