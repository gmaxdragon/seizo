"""Real browser, real local server and real WebGL. No mocked movement or assets."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,time,urllib.request
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence';OUT.mkdir(exist_ok=True)
errors=[];report={'actual_webgl':False,'physical_motion':False}
with tempfile.TemporaryDirectory() as td, (OUT/'browser_server.log').open('w') as log:
 env=dict(os.environ)
 for k in list(env):
  if 'API_KEY' in k:env.pop(k)
 env['SEIZO_PHYSICS_ENGINE']='mujoco'
 proc=subprocess.Popen([sys.executable,'app.py','--port','0','--no-browser','--data-dir',td],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
 try:
  marker=Path(td)/'.running.json'
  for _ in range(300):
   if marker.exists():break
   if proc.poll() is not None:raise RuntimeError('App exited during browser startup')
   time.sleep(.1)
  port=json.loads(marker.read_text())['port'];url=f'http://127.0.0.1:{port}/'
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox'])
   page=browser.new_page(viewport={'width':1280,'height':960},device_scale_factor=.75)
   page.on('pageerror',lambda e:errors.append(str(e)))
   def wait_js(expression,timeout=30000):
    deadline=time.monotonic()+timeout/1000
    while time.monotonic()<deadline:
     if page.evaluate('() => !!('+expression+')'):return
     page.wait_for_timeout(100)
    report['timed_out_predicate']=expression
    report['last_frame']=page.evaluate('window.__seizo?.view?.frame')
    report['status_text']=page.locator('#status').inner_text()
    page.screenshot(path=str(OUT/'last_frame.png'))
    raise TimeoutError(expression)
   page.goto(url,wait_until='networkidle');wait_js('window.__seizo?.view?.renderer?.gl',timeout=30000)
   gl=page.evaluate('''() => {const g=window.__seizo.view.renderer.gl;return {version:g.getParameter(g.VERSION),renderer:g.getParameter(g.RENDERER),lost:g.isContextLost()}}''')
   assert not gl['lost'];report.update(actual_webgl=True,gl=gl)
   page.select_option('#speed','100')
   page.click('#gripperCheck');wait_js('window.__seizo.playback!==null',timeout=30000)
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Open" && window.__seizo.view.frame.pose.gripper>.98')
   page.screenshot(path=str(OUT/'gripper_open.png'))
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Close" && window.__seizo.view.frame.pose.gripper<.01',timeout=90000)
   page.screenshot(path=str(OUT/'gripper_closed.png'))
   page.click('#stop');page.wait_for_timeout(300)
   before=page.evaluate('window.__seizo.view.frame.pose');page.wait_for_timeout(600)
   assert before==page.evaluate('window.__seizo.view.frame.pose');report['stop_holds_pose']=True
   page.select_option('#gripperMode','wrist');page.click('#gripperCheck')
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Clockwise" && window.__seizo.view.frame.pose.wrist>30',timeout=90000)
   wrist=page.evaluate('window.__seizo.view.frame.pose');assert wrist['gripper']>.995
   report['wrist_turn_keeps_jaws_open']=True
   page.click('#stop');page.wait_for_timeout(300)
   page.select_option('#gripperMode','contact');page.click('#gripperCheck')
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Close and squeeze" && window.__seizo.view.frame.gripper_requested_opening<.001',timeout=90000)
   f=page.evaluate('window.__seizo.view.frame')
   assert f['arm_object_contact'] and .3<f['pose']['gripper']<.65
   report['contact']={k:f[k] for k in ['gripper_requested_opening','gripper_actuator_force_nm','arm_object_contact']}
   page.screenshot(path=str(OUT/'gripper_contact.png'));page.click('#stop')
   assert not errors,errors
   report['javascript_errors']=errors;report['result']='pass'
   browser.close()
 finally:
  proc.terminate()
  try:proc.wait(timeout=15)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
  report['javascript_errors']=errors
  (OUT/'browser_gripper.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
