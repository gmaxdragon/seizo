#!/usr/bin/env python3
"""Seizo desktop: install once, fetch verified updates on each launch.

Downloads *application source only* from owner's public GitHub repository.
Never reads or exports Hack Club API keys. Trained weights and local settings
are preserved under one stable folder across all code updates.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

REPO='gmaxdragon/seizo'
BRANCH='seizo-desktop'
BASE_URL=f'https://raw.githubusercontent.com/{REPO}/{BRANCH}'
INSTALL=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'Seizo'/'Studio'
RELEASE_FILE=INSTALL/'.seizo_release.json'
MAX_RESPONSE=3_000_000
MAX_BASE_ARCHIVE=2_000_000
MAX_EXTRACTED=65_000_000
PROTECTED={'.venv','data','logs','.update_backups','__pycache__'}


def sha256(data:bytes)->str:return hashlib.sha256(data).hexdigest()


def urlbytes(url:str,maximum:int=MAX_RESPONSE)->bytes:
    req=urllib.request.Request(url,headers={'User-Agent':'Seizo-Desktop-Updater/1', 'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=40) as response:
        raw=response.read(maximum+1)
    if len(raw)>maximum:raise ValueError('Update file exceeded allowed size')
    return raw


def manifest_url():return BASE_URL+'/desktop_manifest.json?refresh='+str(int(time.time()))


def validated_manifest(doc):
    if not isinstance(doc,dict) or doc.get('schema')!='seizo-desktop-manifest/v1':raise ValueError('Unexpected manifest schema')
    v=doc.get('version');base=doc.get('base');files=doc.get('patches')
    if not isinstance(v,str) or len(v)>80 or not v or not v.replace('-','').replace('.','').replace('_','').isalnum():raise ValueError('Invalid version')
    if not isinstance(base,dict) or not isinstance(files,dict) or not 1<=len(files)<=80:raise ValueError('Invalid release manifest')
    for item in [base,*files.values()]:
        if not isinstance(item,dict) or not isinstance(item.get('sha256'),str) or len(item['sha256'])!=64:
            raise ValueError('Invalid expected checksum')
        if not isinstance(item.get('url'),str) or not item['url'].startswith('https://raw.githubusercontent.com/gmaxdragon/seizo/'):
            raise ValueError('Only project GitHub source URLs are permitted')
    for name in files:
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] in PROTECTED or str(p).startswith('.'):
            raise ValueError('Unsafe update path')
        if name.startswith('web/assets/') and p.suffix not in ('.json','.glb'):
            raise ValueError('Unexpected asset extension')
    return doc


def base_extract(data:bytes,target:Path):
    target.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:xz') as arc:
        members=arc.getmembers();total=0
        for m in members:
            p=Path(m.name)
            if (not p.parts or p.parts[0]!='Seizo_Learn' or '..' in p.parts
                    or p.is_absolute() or m.issym() or m.islnk() or (not m.isdir() and not m.isfile())):
                raise ValueError('Unsafe archive member')
            if m.isfile():
                total+=m.size
                if total>MAX_EXTRACTED or m.size>MAX_EXTRACTED:raise ValueError('Unusually large source bundle')
        for m in members:
            p=Path(m.name)
            if m.isdir(): (target/p).mkdir(parents=True,exist_ok=True)
            else:
                out=target/p;out.parent.mkdir(parents=True,exist_ok=True)
                with arc.extractfile(m) as source, out.open('wb') as sink:
                    shutil.copyfileobj(source,sink)
    if not (target/'Seizo_Learn/app.py').is_file():raise ValueError('Base package lacks the application entrypoint')


def current_version():
    try:return json.loads(RELEASE_FILE.read_text(encoding='utf-8')).get('version')
    except (OSError,ValueError):return None


def already_running():
    try:
        from urllib.request import ProxyHandler,build_opener
        running=json.loads((INSTALL/'data/.running.json').read_text(encoding='utf-8'))
        port=int(running['port']);expected=running.get('instance')
        if not 1<=port<=65535:return False
        client=build_opener(ProxyHandler({}))
        with client.open('http://127.0.0.1:'+str(port)+'/healthz',timeout=1) as response:
            value=json.loads(response.read(1024))
        return bool(value.get('ready') and value.get('instance')==expected)
    except Exception:return False


def update_from_manifest(manifest):
    """Stage everything and check hashes BEFORE modifying the installation."""
    version=manifest['version']
    if already_running():
        print('Seizo is already open. Close its terminal to apply updates; opening existing version.',flush=True)
        return False
    if current_version()==version and (INSTALL/'app.py').is_file():
        # On every launch, verify the patched files. Redownload only if needed.
        okay=all((INSTALL/name).is_file() and sha256((INSTALL/name).read_bytes())==v['sha256'] for name,v in manifest['patches'].items())
        if okay:print('Seizo code is already up to date.',flush=True);return False
    with tempfile.TemporaryDirectory(prefix='seizo-release-') as tmp:
        staging=Path(tmp)/'stage';staging.mkdir()
        if not (INSTALL/'app.py').exists():
            archive=urlbytes(manifest['base']['url'],MAX_BASE_ARCHIVE)
            if sha256(archive)!=manifest['base']['sha256']:raise ValueError('Base source bundle SHA mismatch')
            base_extract(archive,staging)
        base_dir=staging/'Seizo_Learn'
        for name,entry in manifest['patches'].items():
            content=urlbytes(entry['url'])
            if sha256(content)!=entry['sha256']:raise ValueError('Source SHA mismatch for '+name)
            p=base_dir/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(content)
        # Keep checkpoint data, credentials, cached virtualenv and logs untouched.
        installed=0;backups=[]
        for source in sorted(base_dir.rglob('*')):
            if not source.is_file():continue
            name=source.relative_to(base_dir)
            if name.parts[0] in PROTECTED:continue
            dest=INSTALL/name;dest.parent.mkdir(parents=True,exist_ok=True)
            data=source.read_bytes()
            if dest.is_file() and sha256(dest.read_bytes())==sha256(data):continue
            old=None
            if dest.exists():
                old=INSTALL/'.update_backups'/version/name
                old.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(dest,old)
            staged=dest.with_name(dest.name+'.seizo-next')
            staged.write_bytes(data)
            try:os.replace(staged,dest)
            except Exception:
                staged.unlink(missing_ok=True)
                for path,saved in reversed(backups):
                    if saved and saved.exists():shutil.copy2(saved,path)
                    else:path.unlink(missing_ok=True)
                raise
            backups.append((dest,old))
            installed+=1
        RELEASE_FILE.parent.mkdir(parents=True,exist_ok=True)
        temporary=RELEASE_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':version,'installed_utc':time.time(),'files_updated':installed},indent=2),encoding='utf-8')
        os.replace(temporary,RELEASE_FILE)
        print(f'Installed Seizo {version}: {installed} source files updated. Your training data was preserved.',flush=True)
        return True


def main():
    if sys.version_info<(3,10) or sys.maxsize<2**32:raise RuntimeError('Use 64-bit Python 3.10 or newer.')
    print('SEIZO DESKTOP. One stable folder; automatic updates.',flush=True)
    cached=(INSTALL/'app.py').is_file()
    try:
        info=validated_manifest(json.loads(urlbytes(manifest_url(),128000)))
        update_from_manifest(info)
    except Exception as e:
        print('Update unavailable: '+str(e)[:350],flush=True)
        if not cached:raise RuntimeError('First installation requires a working connection to GitHub. Nothing was installed.') from e
        print('Using the last verified local copy instead. No files or training data were erased.',flush=True)
    print('Starting local Seizo. Keep this window open. Stop & Save before exiting.',flush=True)
    return subprocess.call([sys.executable,str(INSTALL/'bootstrap.py')],cwd=INSTALL)


if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:print('Interrupted. Training should be saved using STOP & save.',flush=True);sys.exit(1)
    except Exception as e:print('Could not start: '+str(e),file=sys.stderr);sys.exit(1)
