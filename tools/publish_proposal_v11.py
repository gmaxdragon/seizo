"""Package only byte-identical, cross-platform-tested no-motion release source.

Updates the candidate branch only. Stable promotion requires a separate explicit
expected-head update after the returned artifact has been independently checked.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from prepare_proposal_release_v11 import make_manifest

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
BRANCH='seizo-proposal-release-v11'
assert os.environ['GITHUB_REF']=='refs/heads/'+BRANCH
expected_sha=os.environ['GITHUB_SHA']

def git(*args):return subprocess.check_output(['git',*args],text=True).strip()

local=json.loads((ROOT/'release-source-hashes.json').read_text())
for platform in ('Linux','Windows'):
    found=json.loads((ROOT/'verified-evidence'/('v11-evidence-'+platform)/'release-source-hashes.json').read_text())
    differences=[k for k in set(local)|set(found) if local.get(k)!=found.get(k)]
    assert not differences, 'Tested source differs on '+platform+': '+repr(differences)
assert git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==expected_sha,'Release branch changed during tests'
subprocess.run(['git','config','user.name','github-actions[bot]'],check=True)
subprocess.run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],check=True)
subprocess.run(['git','add','--','patches','seizo_updater.py','docs/PROPOSAL_BRIDGE_V11_RELEASE.md'],check=True)
subprocess.run(['git','commit','-m','Package tested Seizo v11 source; real arm locked'],check=True)
source=git('rev-parse','HEAD')
manifest=make_manifest(source)
manifest_raw=(json.dumps(manifest,separators=(',',':'))+'\n').encode()
(ROOT/'desktop_manifest.json').write_bytes(manifest_raw)
for filename in ('seizo_updater.py','release-legacy-updater.py'):
    spec=importlib.util.spec_from_file_location('package_updater_check',ROOT/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.validated_manifest(manifest)
for name,entry in manifest['patches'].items():
    assert hashlib.sha256((ROOT/'patches'/name).read_bytes()).hexdigest()==entry['sha256']
proof={'version':manifest['version'],'source_commit':source,'tested_workflow_commit':expected_sha,
       'patch_tree':git('rev-parse','HEAD:patches'),'patch_count':len(manifest['patches']),
       'manifest_sha256':hashlib.sha256(manifest_raw).hexdigest(),'source_hashes':local,
       'legacy_updater_blob':'38324420ca3000331a906bbef78a45ab6fe35c83',
       'legacy_updater_manifest_accepted':True,'real_pi_connected':False,
       'automatic_motion_enabled':False,'authorized':False,'executed':False,'physically_verified':False,
       'note':'Linux and Windows tests passed. Browser uses mocked intent and synthetic passing scores. Stable promotion separate.'}
(ROOT/'release-proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
subprocess.run(['git','add','desktop_manifest.json','release-proof.json'],check=True)
subprocess.run(['git','commit','-m','Pin v11 manifest compatible with the original START_SEIZO updater'],check=True)
subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],check=True)
print(json.dumps({'candidate_commit':git('rev-parse','HEAD'),**proof}))
