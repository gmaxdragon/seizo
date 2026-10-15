"""Actual local server + Chromium/WebGL control regression. No cloud key used."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,time
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence'
report={'physical_motion':False,'cloud_requests':0};errors=[]
with tempfile.TemporaryDirectory() as td,(OUT/'browser_roll_server.log').open('w') as log:
 env={k:v for k,v in os.environ.items() if 'API_KEY' not in k};env['SEIZO_PHYSICS_ENGINE']='mujoco';env['OPENBLAS_NUM_THREADS']='1'
 p=subprocess.Popen([sys.executable,'app.py','--port','0','--no-browser','--data-dir',td],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
 try:
  marker=Path(td)/'.running.json'
  for _ in range(200):
   if marker.exists():break
   if p.poll() is not None:raise RuntimeError('Server exited: '+(OUT/'browser_roll_server.log').read_text())
   time.sleep(.1)
  url='http://127.0.0.1:'+str(json.loads(marker.read_text())['port'])
  with sync_playwright() as pw:
   opts={'headless':True,'args':['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']}
   if Path('/usr/bin/chromium').exists():opts['executable_path']='/usr/bin/chromium'
   b=pw.chromium.launch(**opts);page=b.new_page(viewport={'width':1366,'height':1200},device_scale_factor=1)
   page.on('pageerror',lambda e:errors.append(str(e)))
   def wait_js(s,timeout=60):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
     if page.evaluate('() => !!('+s+')'):return
     page.wait_for_timeout(100)
    report['failed_wait']=s;report['last_frame']=page.evaluate('window.__seizo?.view?.frame')
    page.screenshot(path=str(OUT/'roll_failure.png'));raise TimeoutError(s)
   page.goto(url,wait_until='networkidle');wait_js('window.__seizo?.view?.renderer?.gl')
   report['webgl']=page.evaluate('window.__seizo.view.renderer.gl.getParameter(window.__seizo.view.renderer.gl.VERSION)')
   page.select_option('#speed','100');page.select_option('#gripperMode','wrist');page.click('#gripperCheck')
   wait_js('window.__seizo?.view?.frame?.diagnostic_phase==="Roll 90 degrees" && window.__seizo.view.frame.pose.wrist>88',90)
   f90=page.evaluate('window.__seizo.view.frame');assert f90['pose']['gripper']>.995;assert not f90['gripper_object_contact']
   page.locator('.viewport').screenshot(path=str(OUT/'roll_90.png'))
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Roll 180 degrees" && window.__seizo.view.frame.pose.wrist>178',60)
   page.locator('.viewport').screenshot(path=str(OUT/'roll_180.png'))
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Roll 360 degrees" && window.__seizo.view.frame.pose.wrist>359',90)
   f360=page.evaluate('window.__seizo.view.frame');page.locator('.viewport').screenshot(path=str(OUT/'roll_360.png'))
   report['roll']={'at90':f90['pose']['wrist'],'at360':f360['pose']['wrist'],'opening_at360':f360['pose']['gripper'],
                    'contact_at90':f90['gripper_object_contact'],'contact_at360':f360['gripper_object_contact']}
   page.click('#stop');page.wait_for_timeout(500);pose=page.evaluate('window.__seizo.view.frame.pose');page.wait_for_timeout(500)
   assert pose==page.evaluate('window.__seizo.view.frame.pose');report['stop_holds']=True
   page.select_option('#gripperMode','open_close');page.click('#gripperCheck')
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Close" && window.__seizo.view.frame.pose.gripper<.01',90)
   empty=page.evaluate('window.__seizo.view.frame');assert not empty['gripper_contact_continues'];assert not empty['arm_object_contact']
   report['empty_contact']=empty['contacts'];page.locator('.viewport').screenshot(path=str(OUT/'empty_closed.png'));page.click('#stop');page.wait_for_timeout(400)
   page.select_option('#gripperMode','contact');page.click('#gripperCheck')
   wait_js('window.__seizo.view.frame.diagnostic_phase==="Close and squeeze" && window.__seizo.view.frame.gripper_requested_opening<.001',90)
   f=page.evaluate('window.__seizo.view.frame');assert f['gripper_object_contact'];assert f['gripper_contact_continues']
   assert any('object_red' in (a['a'],a['b']) for a in f['contacts']['pairs'])
   report['real_contact']=f['contacts'];page.locator('.viewport').screenshot(path=str(OUT/'squeeze_actual_block.png'));page.click('#stop');page.wait_for_timeout(400)
   assert len(page.locator('#task option').all())==9
   page.click('#settingsOpen');page.select_option('#evalTrials','5');page.fill('#episodes','2');page.select_option('#compute','fast');page.click('#settingsClose')
   page.select_option('#task','orient');page.click('#train')
   # Some prompts are browser confirm; accept them below if used.
   wait_js('window.__seizo?.snapshot?.status === "complete"',45) if False else None
   # Query the real local API via the app token, not a mock response.
   def api_state():return page.evaluate("async () => (await fetch('/api/status',{headers:{'X-Lab-Token':document.querySelector('meta[name=lab-token]').content}})).json()")
   start=time.monotonic()
   while time.monotonic()-start<60:
    state=api_state()
    if state.get('status')=='complete':break
    if state.get('status')=='error':raise RuntimeError(state)
    page.wait_for_timeout(250)
   assert state['updates']>0 and state['weights_changed_from_initial'],state
   report['training']={k:state[k] for k in ('episodes','moves','updates','weights_changed_from_initial')}
   page.click('#stop');page.wait_for_timeout(500);page.click('#evaluate')
   start=time.monotonic()
   while time.monotonic()-start<180:
    state=api_state()
    if state.get('evaluation'):break
    if state.get('status')=='error':raise RuntimeError(state)
    page.wait_for_timeout(500)
   assert len(state['evaluation']['by_task'])==7,state
   report['evaluation']={'tasks':7,'current':state['evaluation']['current'],'random':state['evaluation']['random_actions']}
   assert '0 request attempts' in page.locator('#apiActivity').inner_text(),page.locator('#apiActivity').inner_text()
   page.screenshot(path=str(OUT/'roll_v6_application.png'),full_page=True)
   report['javascript_errors']=errors;assert not errors,errors;report['result']='pass';b.close()
 finally:
  p.terminate()
  try:p.wait(15)
  except subprocess.TimeoutExpired:p.kill();p.wait(5)
  (OUT/'browser_roll_v6.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
