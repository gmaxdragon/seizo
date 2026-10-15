"""Apply verified source edits; compressed input is JSON data, not executed code."""
from pathlib import Path,PurePosixPath
import base64,hashlib,json,lzma,shutil,tarfile
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='47baac02f75213f9537d0f31e97b13ac543ae1c15706ccec5dfd347be062afe8'
raw=base64.b64decode(''.join((ROOT/'run-v10-transfer'/f'part{i}.txt').read_text().strip() for i in range(4)),validate=True)
assert hashlib.sha256(raw).hexdigest()==EXPECTED,'Source transport checksum mismatch'
source=json.loads(lzma.decompress(raw))
assert source['schema']=='seizo-exact-source-delta/v1'
with tarfile.open(ROOT/'Seizo_Learn_Web.tar.xz','r:xz') as archive:archive.extractall(ROOT,filter='data')
app=ROOT/'Seizo_Learn'
shutil.copytree(ROOT/'patches',app,dirs_exist_ok=True)
for name,change in source['changes'].items():
    rel=PurePosixPath(name)
    assert not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] not in ('.git','.github','data'),name
    target=app/name
    if 'new' in change:text=change['new']
    else:
        assert hashlib.sha256(target.read_bytes()).hexdigest()==change['base_sha256'],'Unexpected baseline: '+name
        lines=target.read_text(encoding='utf-8').splitlines(keepends=True)
        for start,end,replacement in reversed(change['edits']):lines[start:end]=replacement
        text=''.join(lines)
    data=text.encode('utf-8')
    assert hashlib.sha256(data).hexdigest()==change['sha256'],'Changed source mismatch: '+name
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
(app/'evidence').mkdir(exist_ok=True)
(ROOT/'v10_paths.json').write_text(json.dumps(list(source['changes']),indent=2)+'\n')
print('Verified',len(source['changes']),'source edits; existing policy identity and data paths preserved.')
