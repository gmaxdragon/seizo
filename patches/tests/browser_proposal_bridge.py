"""Real browser + original rendered policy + loopback. Intent/scores are fixtures."""
from pathlib import Path
import os,sys,json,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
from playwright.sync_api import sync_playwright
from app import Server,make_handler,default_runner
from core.cloud import HackClubPlanner
from core.proposal_protocol import parse_intent,canonical,INTENT_SCHEMA
from test_proposal_integration import report_fixture
root=Path(__file__).resolve().parents[1];out=root/'evidence';out.mkdir(exist_ok=True)
class IntentFixture(HackClubPlanner):
 def __init__(self):
  super().__init__();self.calls=0;self.block=False;self.entered=threading.Event();self.release=threading.Event()
 def interpret_task(self,instruction,model):
  self.calls+=1;self.entered.set()
  if self.block:self.release.wait(20.)
  return parse_intent(canonical({'schema':INTENT_SCHEMA,'status':'supported','task':'lift','target':'red_cube'})),{'fixture_not_api':True}
with tempfile.TemporaryDirectory() as td:
 r=default_runner(td);cloud=IntentFixture();quit_event=threading.Event()
 # A real numerical update with synthetic observations tests plumbing only.
 x=np.zeros((2,r.agent.obs_size),np.float32);_,z,lp,_=r.agent.act(x)
 r.agent.update((x,z,lp,np.array([-1,1],np.float32),np.array([0,1],np.float32)),epochs=1)
 r.save();r.status='paused';report_fixture(r.folder,r.agent,r.camera_config)
 checkpoint=r.folder/'policy.npz';before=checkpoint.read_bytes()
 server=Server(('127.0.0.1',0),make_handler(r,'browser-fixture-token',quit_event,cloud,'proposal-browser'))
 th=threading.Thread(target=server.serve_forever,daemon=True);th.start();errors=[]
 try:
  with sync_playwright() as p:
   executable=os.environ.get('SEIZO_TEST_CHROMIUM')
   browser=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),
     args=['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--use-angle=swiftshader'])
   page=browser.new_page(viewport={'width':1400,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
   page.wait_for_function("() => document.getElementById('wristFrame').naturalWidth>0",timeout=60000)
   page.locator('#proposalPanel summary').click()
   page.locator('#proposalInstruction').fill('Lift the red cube')
   page.locator('#proposalPrepare').click()
   page.wait_for_function("() => document.getElementById('proposalState').textContent.includes('Received by mock Pi')",timeout=60000)
   assert 'sim_degree' in page.locator('#proposalActions').inner_text()
   assert 'not connected' in page.locator('#proposalPhysical').inner_text()
   assert 'Executed: no' in page.locator('#proposalPhysical').inner_text()
   page.locator('#proposalPanel').screenshot(path=str(out/'proposal_receipt.png'))
   assert checkpoint.read_bytes()==before
   checkpoint.unlink();page.locator('#proposalPrepare').click()
   page.wait_for_function("() => document.getElementById('proposalState').textContent.includes('saved_checkpoint_missing')",timeout=15000)
   assert cloud.calls==1
   checkpoint.write_bytes(before);cloud.block=True;cloud.entered.clear()
   page.locator('#proposalPrepare').click()
   assert cloud.entered.wait(10.)
   started=time.perf_counter()
   with page.expect_response(lambda x:x.url.endswith('/api/proposal/stop'),timeout=5000) as response:
    page.locator('#proposalStop').click()
   ack=response.value.json();stop_seconds=time.perf_counter()-started
   assert ack['ok'] and ack['automatic_motion_enabled'] is False
   assert not cloud.release.is_set()
   cloud.release.set()
   page.wait_for_function("() => !document.getElementById('proposalPrepare').disabled",timeout=15000)
   page.reload(wait_until='domcontentloaded');page.wait_for_timeout(1500)
   assert cloud.calls==2, 'Reload must not resubmit the instruction'
   assert checkpoint.read_bytes()==before
   assert not errors,errors
   result={'scope':'Software integration only. Cloud intent and passing scores are SYNTHETIC fixtures, not skill evidence.',
     'browser':'actual Chromium/WebGL','real_rendered_camera_input':True,'original_saved_ppo_inference':True,
     'actual_loopback_receipt':True,'checkpoint_bytes_unchanged':True,'missing_checkpoint_blocks_cloud':True,
     'stop_ack_seconds_while_cloud_blocked':stop_seconds,'reload_did_not_resubmit':True,
     'javascript_errors':errors,'actual_cloud_requests':cloud._requests,'real_pi_connected':False,
     'simulated_steps_executed':0,'authorized':False,'executed':False,'physically_verified':False}
   (out/'browser_proposal_bridge.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
   browser.close()
 finally:
  cloud.release.set();r.shutdown();server.shutdown();server.server_close()
