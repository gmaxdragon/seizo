"""Start from any working directory; diagnose dependencies before opening a page."""
from __future__ import annotations
from pathlib import Path
import os
import re
import struct
import subprocess
import sys
import time
import venv

ROOT=Path(__file__).resolve().parent
LOG=ROOT/'logs'/'startup.log'


def safe_log(text):
    # The app never prints a submitted API key. Redact common token/URL patterns
    # too, in case pip reports a proxy URL from the user's environment.
    text=re.sub(r'(?i)(Bearer\s+)\S+',r'\1[redacted]',str(text))
    text=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[redacted]',text)
    text=re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@',r'\1[redacted]@',text)
    return text


def report(text):
    text=safe_log(text)
    print(text,flush=True)
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(text+'\n')


def numpy_ok(python):
    try:
        result=subprocess.run([str(python),'-c',
            'import sys,struct; assert sys.version_info>=(3,10) and struct.calcsize("P")==8; import numpy as n; assert int(n.__version__.split(".")[0])<3; n.zeros((2,2))'],
            capture_output=True,timeout=25,cwd=ROOT)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def python_ok(python):
    try:
        result=subprocess.run([str(python),'-c','import sys; print(sys.executable)'],capture_output=True,timeout=15,cwd=ROOT)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def run_logged(command):
    env=os.environ.copy();env['PYTHONUNBUFFERED']='1';env['PYTHONIOENCODING']='utf-8'
    with subprocess.Popen([str(v) for v in command],cwd=ROOT,env=env,stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace') as process:
        for line in process.stdout:report(line.rstrip('\r\n'))
        return process.wait()


def choose_python():
    if sys.version_info<(3,10) or struct.calcsize('P')!=8:
        raise RuntimeError('Install 64-bit Python 3.10 or newer from https://www.python.org/downloads/windows/.')
    for item in ('app.py','web/index.html','web/app.js','web/assets/meshes.json'):
        if not (ROOT/item).is_file():
            raise RuntimeError('The download is not fully extracted. Use Extract All and run START.bat inside the extracted Seizo_Learn folder.')
    target=ROOT/'.venv'
    python=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if numpy_ok(python):
        report('Using this folder\'s working Python environment.');return python
    if numpy_ok(sys.executable):
        report('Python and NumPy are already available. No package download needed.');return Path(sys.executable)
    if target.exists() and not python_ok(python):
        backup=ROOT/('.venv-old-'+str(time.time_ns()))
        report('Repairing a stale Python environment. Saved policies are NOT touched.')
        target.rename(backup)
    if not python.exists():
        report('First setup: creating a private environment. Please keep this window open.')
        venv.EnvBuilder(with_pip=True).create(target)
    if not numpy_ok(python):
        report('Installing NumPy. Internet is needed for this one-time step; no AI model is downloaded.')
        rc=run_logged([python,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',
                       '--retries','1','--timeout','30','-r',ROOT/'requirements.txt'])
        if rc or not numpy_ok(python):
            raise RuntimeError('NumPy setup failed. No browser was opened. Check the message above. Retry START.bat with internet; do not disable antivirus.')
    return python



def prepare_rigid_body_engine(python):
    """Install the free CPU physics engine once. Never delete saved weights.

    No physical robot drivers are installed or enabled. An unavailable wheel
    leaves viewing available but blocks realistic training/checks in the HTTP API.
    """
    if os.environ.get('SEIZO_PHYSICS_ENGINE','auto').lower()=='capsule':
        raise RuntimeError('This release trains from simulated camera images and requires MuJoCo. Run the normal START_SEIZO.bat, not the old diagnostic capsule mode.')
    try:
        check=subprocess.run([str(python),'-c','import mujoco; m=mujoco.MjModel.from_xml_string("<mujoco><worldbody/></mujoco>");print(m.nbody)'],
                             timeout=20,capture_output=True,text=True)
        if check.returncode==0:
            report('Realistic MuJoCo rigid-body physics is installed.');return
    except (OSError,subprocess.TimeoutExpired):pass
    failed_flag=ROOT/'data'/'mujoco_install_failed.txt'
    if failed_flag.exists() and os.environ.get('SEIZO_RETRY_PHYSICS_INSTALL')!='1':
        report('MuJoCo was previously unavailable. Training is blocked. Set SEIZO_RETRY_PHYSICS_INSTALL=1 to retry.');return
    report('One-time setup: installing free MuJoCo rigid-body physics; this may take a few minutes.')
    result=run_logged([python,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',
                       '--retries','1','--timeout','30','mujoco==3.3.7'])
    if result:
        failed_flag.parent.mkdir(exist_ok=True,parents=True)
        failed_flag.write_text('MuJoCo install failed. Use SEIZO_RETRY_PHYSICS_INSTALL=1 to retry.\n',encoding='utf-8')
        report('MuJoCo install did not succeed. Training will remain blocked until MuJoCo installs.');return
    failed_flag.unlink(missing_ok=True)
    report('Realistic MuJoCo physics installed. No external AI inference needed for training.')

def main():
    os.chdir(ROOT)
    LOG.parent.mkdir(parents=True,exist_ok=True)
    # Rotate only logs, never credentials or learning files.
    if LOG.exists() and LOG.stat().st_size>2_000_000:
        LOG.replace(LOG.with_name('startup-previous.log'))
    report('\nSeizo startup '+time.strftime('%Y-%m-%d %H:%M:%S'))
    report('Python '+sys.version.split()[0]+'; application folder: '+str(ROOT))
    python=choose_python()
    prepare_rigid_body_engine(python)
    report('Starting local server. The browser opens only after an actual readiness check.')
    return run_logged([python,'-u',ROOT/'app.py',*sys.argv[1:]])


if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:
        report('Interrupted. Allow any running training to save before closing.');sys.exit(1)
    except Exception as exc:
        try:
            report('STARTUP ERROR: '+str(exc))
            report('No API key is needed to start. Diagnostic log: '+str(LOG))
        except OSError:print('Setup failed: '+str(exc),flush=True)
        sys.exit(1)
