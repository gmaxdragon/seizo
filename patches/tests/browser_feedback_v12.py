"""Real UI, camera training and frozen comparison. No fabricated task scores."""
from pathlib import Path
import sys,tempfile,threading,json,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app import Server,make_handler,default_runner
from core.cloud import HackClubPlanner
root=Path(__file__).resolve().parents[1];out=root/'feedback-evidence';out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as td:
    r=default_runner(td);cloud=HackClubPlanner()
    r.start({'episodes':2,'task':'reach','compute':'fast'});r.thread.join(100)
    assert not r.thread.is_alive() and r.status!='error',r.error
    assert r.feedback.last_update is not None
    server=Server(('127.0.0.1',0),make_handler(r,'feedback-browser-test',threading.Event(),cloud))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--use-angle=swiftshader'])
            page=browser.new_page(viewport={'width':1450,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
            page.wait_for_function("() => document.getElementById('mistakeUpdate').textContent.includes('Actor parameters changed:')",timeout=30000)
            assert 'REAL ARM LOCKED' in page.locator('#physicalLock').inner_text()
            result=page.evaluate("""async()=>{const token=document.querySelector('meta[name="lab-token"]').content;
                const r=await fetch('/api/evaluate',{method:'POST',headers:{'X-Lab-Token':token,'Content-Type':'application/json'},body:JSON.stringify({task:'reach',trials:1})});return r.json()}""")
            assert result.get('ok'),result
            page.wait_for_function("() => document.getElementById('mistakeProof').textContent.includes('small sample not proof')",timeout=100000)
            page.locator('#mistakePanel').screenshot(path=str(out/'learning_feedback.png'))
            assert not errors,errors
            summary={'browser':'actual Chromium','training_transitions':r.feedback.steps,
                     'actor_changed':r.feedback.last_update['actor']['changed_parameters'],
                     'comparison_text':page.locator('#mistakeProof').inner_text(),
                     'errors':errors,'live_cloud_requests':cloud._requests,'physical_motion':False,
                     'scores_are_actual_simulation_outcomes':True}
            (out/'browser.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
            browser.close()
    finally:r.shutdown();server.shutdown();server.server_close()
