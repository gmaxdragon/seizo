"""Prepare the already tested no-motion bridge for the existing desktop updater.

Only release labels, an explicit physical lock banner, the source updater's
camera asset allowlist and release documentation change. No physical runtime.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2026.10.15-proposal-bridge-v11'
BUILD = 'seizo-proposal-bridge-v11'


def replace_once(name, old, new):
    path = ROOT / name
    text = path.read_text(encoding='utf-8')
    if new in text and old not in text:
        return
    assert text.count(old) == 1, name + ': source changed; review required'
    path.write_text(text.replace(old, new), encoding='utf-8', newline='\n')


def prepare():
    replace_once('patches/app.py', "BUILD='seizo-proposal-bridge-dev-v1'", "BUILD='" + BUILD + "'")
    replace_once('patches/tests/test_camera_release.py',
                 "self.assertEqual(BUILD,'seizo-proposal-bridge-dev-v1')",
                 "self.assertEqual(BUILD,'" + BUILD + "')")
    replace_once('patches/web/index.html', '<main><div id="connection"',
                 '<main><section id="physicalLock" role="status" aria-label="Real arm movement lock">'
                 '<strong>REAL ARM LOCKED</strong><p>v11: AI proposals only. Simulation and mock-Pi tests '
                 'do not prove real-arm capability. Physical movement stays disabled until separate '
                 'real-hardware commissioning and local authorization. This app has no motor connection.</p>'
                 '</section><div id="connection"')
    replace_once('patches/tests/browser_proposal_bridge.py',
                 "   page.locator('#proposalPanel summary').click()",
                 "   assert 'REAL ARM LOCKED' in page.locator('#physicalLock').inner_text()\n"
                 "   page.locator('#proposalPanel summary').click()")
    replace_once('seizo_updater.py',
                 "        if name.startswith('web/assets/') and p.suffix not in ('.json','.glb'):",
                 "        if (name.startswith('web/assets/') and p.suffix not in ('.json','.glb')\n"
                 "                and name not in ('web/assets/camera_lod.json.gz',\n"
                 "                                 'web/assets/room_fabric.png', 'web/assets/room_wood.png')):")
    instructions = '''Seizo v11: AI proposals, physical arm locked

Keep using your existing START_SEIZO.bat.
END RUN & SAVE, wait for Saved, close the old terminal, then reopen
START_SEIZO.bat with internet. Verify seizo-proposal-bridge-v11.
No new launcher, manual command copying or new ZIP is required.

Open AI instruction to mock Pi (no motion). Enter one supported task.
The original saved camera PPO proposes one bounded simulator decision.
Missing or incompatible checkpoints and unproven skills are shown as blockers.
No checkpoint upload is required just to install this no-motion release.
Do not reset or delete your training data.

REAL ARM LOCKED. A mock receipt is not permission to move the real arm.
No physical connection, no execution route, no motor commands.
Hardware commissioning and local authorization are separate future work.
STOP here cancels desktop proposals, not the physical robot.
'''
    (ROOT/'patches/START_HERE.txt').write_text(instructions, encoding='utf-8', newline='\n')
    for name in ('README.md', 'RUN_CONTROLS_V10.txt'):
        path = ROOT/'patches'/name
        text = path.read_text(encoding='utf-8')
        heading = 'CURRENT RELEASE: ' + VERSION + '\nSee START_HERE.txt. REAL ARM LOCKED.\n\n'
        if not text.startswith(heading):
            path.write_text(heading + text, encoding='utf-8', newline='\n')
    hashes = source_hashes()
    (ROOT/'release-source-hashes.json').write_text(json.dumps(hashes, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    manifest = make_manifest(os.environ.get('GITHUB_SHA', '4a00624d29e9bf45dbbaeca156b4e689faa1c5ea'))
    (ROOT/'release-candidate-manifest.json').write_text(json.dumps(manifest, separators=(',', ':'))+'\n', encoding='utf-8')


def source_hashes():
    paths = sorted(p for p in (ROOT/'patches').rglob('*') if p.is_file())
    paths += [ROOT/'seizo_updater.py']
    for p in paths:
        assert '__pycache__' not in p.parts and p.suffix not in ('.npz','.pyc'), str(p)
        assert 'data' not in p.relative_to(ROOT).parts, str(p)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def make_manifest(source_sha):
    old = json.loads((ROOT/'desktop_manifest.json').read_text(encoding='utf-8'))
    entries = {}
    for path in sorted((ROOT/'patches').rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(ROOT/'patches').as_posix()
        assert not name.startswith(('.', 'data/', 'logs/')) and '__pycache__' not in name
        entries[name] = {'url': f'https://raw.githubusercontent.com/gmaxdragon/seizo/{source_sha}/patches/{name}',
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert set(old['patches']).issubset(entries), 'Do not silently remove existing patched files'
    assert 1 <= len(entries) <= 80, 'Existing launcher manifest-count compatibility exceeded'
    return {'schema': old['schema'], 'version': VERSION, 'base': old['base'], 'patches': entries}


if __name__ == '__main__':
    prepare()
