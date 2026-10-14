#!/usr/bin/env python3
"""Fetch verified, secret-free Seizo simulator build from public GitHub, then run privately on Railway."""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

BASE='https://raw.githubusercontent.com/gmaxdragon/seizo/3c0e769ccaab7e0d4735fa67533b14bf9ec8c159/'
FILES={
    'Seizo_Learn_Web.tar.xz':'4d639563b67233f68733c57915f7c5aec4568b6a929cd3ff9e7e39112b04da28',
    'railway_host.py':'fcf9daea9882815bb1489ad88039bcb4a2205a40351b3b0bb1620c7a167800e9',
}
ROOT=Path('/srv')
ROOT.mkdir(exist_ok=True)


def download(file):
    with urllib.request.urlopen(BASE+file,timeout=60) as response:
        data=response.read(2_000_001)
    if len(data)>2_000_000 or hashlib.sha256(data).hexdigest()!=FILES[file]:
        raise RuntimeError('Seizo archive checksum mismatch: '+file+' received='+hashlib.sha256(data).hexdigest()+' bytes='+str(len(data)))
    return data


def main():
    # Download before installing: fail closed if source is unavailable or changed.
    bundle=download('Seizo_Learn_Web.tar.xz')
    host=download('railway_host.py')
    with tarfile.open(fileobj=io.BytesIO(bundle),mode='r:xz') as archive:
        for member in archive:
            p=Path(member.name)
            if not p.parts or p.parts[0]!='Seizo_Learn' or '..' in p.parts or member.issym() or member.islnk():
                raise RuntimeError('Unsafe Seizo archive entry')
        archive.extractall(ROOT)
    (ROOT/'railway_host.py').write_bytes(host)
    print('Seizo downloaded and checksummed; installing minimum Python dependency...',flush=True)
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir','numpy>=1.24,<3'],check=True)
    os.execv(sys.executable,[sys.executable,str(ROOT/'railway_host.py')])


if __name__=='__main__':main()