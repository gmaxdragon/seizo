"""Apply a data-only source delta. Nothing here controls real hardware."""
from pathlib import Path, PurePosixPath
import base64, hashlib, json, lzma, shutil, tarfile
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='24484dbac797358066b4291c6582cc3d89b72acf76f76f665f6adff88dae66aa'
parts=[ROOT/'views-v9-transfer'/f'part{i:02d}.txt' for i in range(3)]
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
assets=['web/assets/camera_parts.json','web/assets/camera_lod.json.gz','web/assets/room_wood.png','web/assets/room_fabric.png']
(ROOT/'views-v9-paths.json').write_text(json.dumps(list(source['changes'])+assets,indent=2)+'\n')
(app/'evidence').mkdir(exist_ok=True)
print('Verified',len(source['changes']),'source files. Assets are built separately before tests.')
