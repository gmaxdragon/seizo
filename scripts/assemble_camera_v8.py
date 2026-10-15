"""Apply a data-only source delta, checking baseline and resulting file hashes."""
from pathlib import Path,PurePosixPath
import base64,hashlib,json,lzma,shutil,tarfile
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='3080b55fc88083d66441b06cb6d5addad8d0119df657e30d0e9accdb46021731'
parts=[ROOT/'camera-v8-transfer'/f'part{i:02d}.txt' for i in range(4)]
raw=base64.b64decode(''.join(p.read_text().strip() for p in parts),validate=True)
assert hashlib.sha256(raw).hexdigest()==EXPECTED,'Source transport checksum mismatch'
source=json.loads(lzma.decompress(raw))
assert source['schema']=='seizo-exact-source-delta/v1'
with tarfile.open(ROOT/'Seizo_Learn_Web.tar.xz','r:xz') as archive:
    archive.extractall(ROOT,filter='data')
app=ROOT/'Seizo_Learn'
shutil.copytree(ROOT/'patches',app,dirs_exist_ok=True)
for name,change in source['changes'].items():
    rel=PurePosixPath(name)
    assert not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] not in ('.git','.github','data'),name
    target=app/name
    if 'new' in change:
        text=change['new']
    else:
        assert hashlib.sha256(target.read_bytes()).hexdigest()==change['base_sha256'],'Unexpected baseline: '+name
        lines=target.read_text(encoding='utf-8').splitlines(keepends=True)
        for start,end,replacement in reversed(change['edits']):lines[start:end]=replacement
        text=''.join(lines)
    data=text.encode('utf-8')
    assert hashlib.sha256(data).hexdigest()==change['sha256'],'Changed source mismatch: '+name
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
# Explicit test-only revision. The application's CSP remains strict and unchanged.
browser_test=(ROOT/'ci/browser_camera_v8.py').read_bytes()
assert hashlib.sha256(browser_test).hexdigest()=='227cb6ac00c88d69c93583e513a3b0a47df8efa87af69b0c8bf0b9c6b2e0e02d'
(app/'tests/browser_camera_v8.py').write_bytes(browser_test)
(app/'evidence').mkdir(exist_ok=True)
(ROOT/'camera-v8-paths.json').write_text(json.dumps(list(source['changes']),indent=2)+'\n')
print('Verified',len(source['changes']),'source files. No Pi, Railway or physical motor access.')
