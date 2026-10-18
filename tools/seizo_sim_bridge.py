#!/usr/bin/env python3
"""Standalone, opt-in Seizo simulation observer and bounded command bridge.

Publishes allowlisted simulator telemetry to a PRIVATE GitHub branch. Runs
alongside Seizo v13/v14 without patching, restarting, or reading its NPZ model.
No physical I/O, remote shell, arbitrary URL, API-key upload or public tunnel.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = 'gmaxdragon/SeizoOfficial'
BRANCH = 'desktop-sim-monitor'
MODEL = 'seizo-detailed-view-curriculum-v9'
SCHEMA = 'seizo-sim-monitor/v1'
COMMAND_SCHEMA = 'seizo-sim-command/v1'
HOME = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SeizoSimBridge'
STUDIO = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Seizo' / 'Studio'
TASKS = {'reach', 'orient', 'push', 'lift', 'place', 'rotate', 'orient_place'}
BUSY = {'training', 'stopping', 'evaluating', 'watching'}
POSTS = {'/api/evaluate', '/api/trial', '/api/end-run', '/api/start'}
JSON_LIMIT = 64 * 1024 * 1024


class Blocked(RuntimeError):
    pass


def dump(obj):
    return json.dumps(obj, indent=2, allow_nan=False, sort_keys=True) + '\n'


def atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.next')
    with tmp.open('w', encoding='utf-8') as f:
        f.write(dump(obj)); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def gh_path():
    found = shutil.which('gh')
    candidates = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'GitHub CLI/gh.exe']
    return found or next((str(p) for p in candidates if p.is_file()), None)


class GitHub:
    """gh owns credentials. Never print them, put them on argv, or upload them."""
    def __init__(self):
        self.exe = gh_path()
        if not self.exe:
            raise Blocked('GITHUB_CLI_MISSING')
        self.prefix = 'repos/' + REPO

    def api(self, endpoint, method='GET', body=None):
        if not endpoint.startswith(self.prefix + '/') and endpoint != self.prefix:
            raise Blocked('GITHUB_ENDPOINT_NOT_ALLOWED')
        args = [self.exe, 'api', '--hostname', 'github.com', endpoint, '--method', method]
        if body is not None:
            args += ['--input', '-']
        # A pythonw.exe parent has no console. Without CREATE_NO_WINDOW, every
        # GitHub CLI subprocess can briefly flash a new black window on Windows.
        result = subprocess.run(args, input=None if body is None else dump(body),
                                text=True, encoding='utf-8', capture_output=True,
                                timeout=40, shell=False,
                                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        if result.returncode:
            raise Blocked('GITHUB_REQUEST_FAILED_CHECK_GH_LOGIN_AND_REPO_ACCESS')
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def require_private(self):
        meta = self.api(self.prefix)
        if meta.get('private') is not True or meta.get('full_name') != REPO:
            raise Blocked('MONITOR_REPOSITORY_MUST_BE_PRIVATE')

    def command(self):
        obj = self.api(self.prefix + '/contents/control/command.json?ref=' + BRANCH)
        if obj.get('type') != 'file' or obj.get('size', 99999) > 4096:
            raise Blocked('INVALID_COMMAND_FILE')
        return json.loads(base64.b64decode(obj['content'], validate=False))

    def publish(self, text_files, images):
        """One atomic commit. Preserve concurrent command edits; never force-push."""
        self.require_private()
        ref = self.api(self.prefix + '/git/ref/heads/' + BRANCH)
        parent = ref['object']['sha']
        old = self.api(self.prefix + '/git/commits/' + parent)
        entries = []
        for path, content in text_files.items():
            if not (path in {'README.md', 'latest.json'} or re.fullmatch(r'evaluations/[0-9a-f]{16}\.json', path)):
                raise Blocked('UPLOAD_PATH_NOT_ALLOWED')
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'content': content})
        for name, raw in images.items():
            if name not in {'overhead', 'wrist'}:
                raise Blocked('IMAGE_PATH_NOT_ALLOWED')
            blob = self.api(self.prefix + '/git/blobs', 'POST',
                            {'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
            entries.append({'path': 'images/' + name + '.png', 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        tree = self.api(self.prefix + '/git/trees', 'POST', {'base_tree': old['tree']['sha'], 'tree': entries})
        commit = self.api(self.prefix + '/git/commits', 'POST',
                          {'message': 'Simulation monitor snapshot', 'tree': tree['sha'], 'parents': [parent]})
        self.api(self.prefix + '/git/refs/heads/' + BRANCH, 'PATCH', {'sha': commit['sha'], 'force': False})


class TokenParser(HTMLParser):
    token = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'lab-token':
            self.token = attrs.get('content')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked('LOCAL_REDIRECT_BLOCKED')


class LocalSeizo:
    def __init__(self):
        running = load(STUDIO / 'data/.running.json', {})
        port = running.get('port', 8772)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise Blocked('INVALID_LOCAL_PORT')
        self.base = 'http://127.0.0.1:' + str(port)
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.token = None
        health = self.request('/healthz')
        if health.get('app') != 'SeizoLearn' or health.get('ready') is not True:
            raise Blocked('NOT_SEIZO_SIMULATOR')
        self.instance = health.get('instance')
        parser = TokenParser(); parser.feed(self.request('/', raw=True).decode('utf-8'))
        self.token = parser.token
        if not self.token or len(self.token) > 256:
            raise Blocked('LOCAL_SESSION_TOKEN_UNAVAILABLE')

    def request(self, path, body=None, raw=False):
        allowed = {'/', '/healthz', '/api/status'} if body is None else POSTS
        if path not in allowed:
            raise Blocked('LOCAL_ENDPOINT_NOT_ALLOWED')
        headers = {'X-Lab-Token': self.token or '', 'Origin': self.base,
                   'Content-Type': 'application/json'}
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=None if body is None else dump(body).encode('utf-8'))
        with self.client.open(req, timeout=180 if body is not None else 30) as response:
            if int(response.headers.get('Content-Length', '0')) > JSON_LIMIT:
                raise Blocked('STATUS_TOO_LARGE')
            data = response.read(JSON_LIMIT + 1)
        if len(data) > JSON_LIMIT:
            raise Blocked('STATUS_TOO_LARGE')
        return data if raw else json.loads(data)

    def status(self):
        obj = self.request('/api/status')
        if (obj.get('model_id') != MODEL or obj.get('physical_motion') is not False
                or obj.get('uses_real_cameras') is not False
                or obj.get('input_source') != 'detailed_simulated_cameras'):
            raise Blocked('SIMULATOR_IDENTITY_OR_IMAGE_SOURCE_MISMATCH')
        return obj


def safe_text(value):
    return re.sub(r'[^a-zA-Z0-9 _:.+/-]', '', str(value))[:120]


def finite_number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def evaluation_summary(e):
    if not isinstance(e, dict):
        return None
    out = {'episodes_at_test': finite_number(e.get('episodes_at_test')),
           'fingerprint_unchanged': e.get('fingerprint_unchanged') is True}
    out['policy_fingerprint'] = safe_text(e.get('policy_fingerprint', ''))
    out['tasks'] = []
    for row in e.get('by_task', [])[:7]:
        current = row.get('current', {})
        task = current.get('task')
        if task not in TASKS:
            continue
        record = {'task': task}
        for source in ('current', 'random_actions', 'reference'):
            data = row.get(source, {})
            record[source] = {k: finite_number(data.get(k)) for k in (
                'successes', 'trials', 'invalid_physics', 'faults', 'mean_moves', 'mean_error_mm', 'mean_return')}
            for key in ('failure_counts', 'guard_counts'):
                record[source][key] = {safe_text(k): v for k, v in data.get(key, {}).items()
                                       if type(v) is int and 0 <= v <= 10000}
        out['tasks'].append(record)
    return out


def sanitize(status, instance, bridge_session, last_job, allow_training):
    e = evaluation_summary(status.get('evaluation'))
    return {'schema': SCHEMA, 'observed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'observed_epoch': time.time(), 'online': True, 'app_instance': instance,
            'bridge_session': bridge_session, 'build': safe_text(status.get('build')),
            'status': safe_text(status.get('status')), 'episodes': finite_number(status.get('episodes')),
            'moves': finite_number(status.get('moves')), 'updates': finite_number(status.get('updates')),
            'target_episodes': finite_number(status.get('target_episodes')),
            'policy_fingerprint': safe_text(status.get('policy_fingerprint')),
            'save_verified': status.get('save_verified') is True,
            'evaluation': e, 'last_job': last_job, 'training_commands_allowed': allow_training,
            'simulator_only': True, 'physical_motion': False, 'full_episode_video_recording': False,
            'error_present': bool(status.get('error'))}


def image_payload(status):
    cams = (status.get('live_camera') or {}).get('cameras') or {}
    images = {}
    for name in ('overhead', 'wrist'):
        value = cams.get(name)
        if not isinstance(value, str) or len(value) > 400000:
            continue
        try:
            data = base64.b64decode(value, validate=True)
            if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) <= 300000:
                images[name] = data
        except (ValueError, TypeError):
            continue
    return images


def validate_command(c, report, status, *, now, allow_training=False):
    fields = {'schema', 'id', 'bridge_session', 'app_instance', 'created_at', 'expires_at',
              'policy_fingerprint', 'op', 'task', 'trials', 'episodes'}
    if not isinstance(c, dict) or set(c) - fields or c.get('schema') != COMMAND_SCHEMA:
        raise Blocked('BAD_COMMAND_SCHEMA')
    if not isinstance(c.get('id'), str) or not re.fullmatch(r'[0-9a-f-]{36}', c['id']):
        raise Blocked('BAD_COMMAND_ID')
    if c.get('bridge_session') != report['bridge_session'] or c.get('app_instance') != report['app_instance']:
        raise Blocked('STALE_SESSION')
    begin, expiry = c.get('created_at'), c.get('expires_at')
    if (finite_number(begin) is None or finite_number(expiry) is None
            or not begin <= now < expiry <= begin + 600 or now - begin > 600):
        raise Blocked('EXPIRED_COMMAND')
    op = c.get('op')
    if op not in {'evaluate', 'watch', 'stop_save', 'train'}:
        raise Blocked('OPERATION_NOT_ALLOWED')
    if op != 'stop_save':
        if status.get('status') in BUSY or status.get('status') == 'error':
            raise Blocked('SIMULATOR_BUSY_OR_ERROR_NO_RETRY')
        if (status.get('end_run') or {}).get('state') in {'requested', 'saving'}:
            raise Blocked('SAVE_IN_PROGRESS')
        if c.get('policy_fingerprint') != status.get('policy_fingerprint'):
            raise Blocked('CHECKPOINT_CHANGED')
    if op == 'stop_save':
        return '/api/end-run', {'control_seq': int(time.time() * 1_000_000)}
    if c.get('task') != 'reach':
        raise Blocked('ONLY_REACH_WHILE_MILESTONE_2')
    if op == 'evaluate':
        if type(c.get('trials')) is not int or not 1 <= c['trials'] <= 5:
            raise Blocked('EVALUATION_LIMIT_5')
        return '/api/evaluate', {'task': 'reach', 'trials': c['trials']}
    if op == 'watch':
        return '/api/trial', {'task': 'reach', 'source': 'current', 'fault': False}
    if not allow_training:
        raise Blocked('TRAINING_NEEDS_LOCAL_OPT_IN')
    if type(c.get('episodes')) is not int or not 1 <= c['episodes'] <= 20:
        raise Blocked('TRAINING_LIMIT_20')
    if (status.get('status') == 'paused' and status.get('config', {}).get('task') == 'reach'
            and status.get('config', {}).get('episodes') == c['episodes']
            and status.get('target_episodes', 0) - status.get('episodes', 0) > c['episodes']):
        raise Blocked('EXISTING_RESUME_BUDGET_TOO_LARGE')
    return '/api/start', {'task': 'reach', 'episodes': c['episodes'], 'compute': 'cad',
                          'fault_probability': 0, 'control_seq': int(time.time() * 1_000_000)}


def readme(report, have_images=False, image_epoch=None):
    e = report.get('evaluation') or {}
    lines = ['# Seizo simulation monitor', '',
             '**Last PC report:** ' + report['observed_utc'],
             '**PC connection at that time:** ' + ('online' if report['online'] else 'offline'),
             'Refresh this page. A report older than 3 minutes is stale, not proof of an active run.', '',
             '| Item | Latest report |', '| --- | --- |']
    for k in ('status', 'episodes', 'updates', 'moves', 'save_verified', 'training_commands_allowed'):
        lines.append('| ' + k + ' | ' + str(report.get(k, 'unknown')) + ' |')
    lines += ['', '## Frozen evaluation', '| Task | Successes | Trials | Guard endings |', '| --- | ---: | ---: | ---: |']
    for row in e.get('tasks', []):
        c = row['current']
        lines.append(f"| {row['task']} | {c.get('successes')} | {c.get('trials')} | {c.get('invalid_physics')} |")
    if have_images:
        lines += ['', '## Sampled SIMULATED camera images', 'Snapshot epoch: ' + str(image_epoch),
                  'These are periodic samples, not live video and not physical Pi cameras.',
                  '![Simulated overhead](images/overhead.png)', '![Simulated wrist](images/wrist.png)']
    lines += ['', '## Access and limits', 'Private report. Your PC performs the computation.',
              'ChatGPT can read latest.json and queue allowlisted commands in control/command.json.',
              'No raw shell, reset, cloud-key control, physical I/O or Pi access is accepted.',
              'Train commands are disabled unless you explicitly enable them locally.',
              'Every observed completed evaluation is archived. This is not complete video capture of every episode.',
              '## Latest command receipt', '```json', dump(report.get('last_job')), '```']
    return '\n\n'.join(lines) + '\n'


def main_loop(once=False):
    HOME.mkdir(parents=True, exist_ok=True)
    lock = (HOME / 'bridge.lock').open('a+b'); lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError: raise Blocked('BRIDGE_ALREADY_RUNNING')
    else:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    github = GitHub(); github.require_private()
    session = str(uuid.uuid4())
    journal = load(HOME / 'journal.json', {'handled': [], 'last_job': None, 'day': '', 'training_spent': 0})
    cfg = load(HOME / 'config.json', {})
    images_at = None; have_images = False
    print('Phone report: https://github.com/' + REPO + '/tree/' + BRANCH, flush=True)
    while not (HOME / 'DISABLED').exists():
        now = time.time()
        report = {'schema': SCHEMA, 'online': False, 'observed_epoch': now,
                  'observed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'bridge_session': session, 'last_job': journal['last_job'],
                  'simulator_only': True, 'physical_motion': False}
        try:
            github.require_private()
            try:
                local = LocalSeizo(); status = local.status()
            except (OSError, ValueError, Blocked):
                local = None
            images = {}; files = {}
            if local is not None:
                report = sanitize(status, local.instance, session, journal['last_job'], bool(cfg.get('allow_training')))
                command = github.command()
                ident = command.get('id') if isinstance(command, dict) else None
                if ident and ident not in journal['handled']:
                    journal['handled'].append(ident)
                    receipt = {'id': safe_text(ident), 'state': 'claimed'}
                    journal['last_job'] = receipt; atomic(HOME / 'journal.json', journal)
                    try:
                        status = local.status()
                        route, body = validate_command(command, report, status, now=time.time(),
                                                       allow_training=bool(cfg.get('allow_training')))
                        today = time.strftime('%Y-%m-%d', time.gmtime())
                        if journal['day'] != today:
                            journal.update(day=today, training_spent=0)
                        if command['op'] == 'train':
                            if journal['training_spent'] + command['episodes'] > 100:
                                raise Blocked('TRAINING_DAILY_LIMIT_100')
                            journal['training_spent'] += command['episodes']
                        atomic(HOME / 'journal.json', journal)
                        response = local.request(route, body)
                        receipt['state'] = 'request_acknowledged_not_completion'
                        if command['op'] == 'watch':
                            receipt.update(state='watch_completed', success=response.get('success') is True,
                                           moves=finite_number(response.get('episode_moves')),
                                           guard=safe_text(response.get('safety_abort', '')))
                    except Blocked as e:
                        receipt.update(state='rejected', reason=str(e))
                    except Exception:
                        receipt.update(state='uncertain_do_not_retry', reason='CHECK_CURRENT_SIMULATOR_STATUS')
                    journal['last_job'] = receipt; atomic(HOME / 'journal.json', journal)
                    report['last_job'] = receipt
                if images_at is None or now - images_at >= 300:
                    images = image_payload(status)
                    if len(images) == 2: images_at = now; have_images = True
                evaluation = report.get('evaluation')
                if evaluation:
                    text = dump(evaluation)
                    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                    files['evaluations/' + digest + '.json'] = text
            report.update(image_snapshot_epoch=images_at, report_interval_seconds=60)
            files.update({'latest.json': dump(report), 'README.md': readme(report, have_images, images_at)})
            github.publish(files, images)
            atomic(HOME / 'local_status.json', report)
            print('SYNCED ' + report['observed_utc'] + ' ' + str(report.get('status', 'offline')), flush=True)
        except Exception as e:
            atomic(HOME / 'bridge_error.json', {'epoch': time.time(), 'error_type': type(e).__name__,
                                               'code': str(e) if isinstance(e, Blocked) else 'SYNC_FAILED'})
        if once: break
        time.sleep(60)
    lock.close()


def install(allow_training=False):
    if os.name != 'nt': raise Blocked('INSTALLER_REQUIRES_WINDOWS')
    github = GitHub(); github.require_private()
    HOME.mkdir(parents=True, exist_ok=True)
    target = HOME / 'seizo_sim_bridge.py'
    if Path(__file__).resolve() != target.resolve():
        shutil.copy2(__file__, target)
    atomic(HOME / 'config.json', {'allow_training': bool(allow_training)})
    (HOME / 'DISABLED').unlink(missing_ok=True)
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    python = pythonw if pythonw.is_file() else Path(sys.executable)
    startup = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    startup.mkdir(parents=True, exist_ok=True)
    link = startup / 'Seizo Simulation Bridge.lnk'
    def ps(v): return "'" + str(v).replace("'", "''") + "'"
    command = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + ps(link) + ");"
               "$s.TargetPath=" + ps(python) + ";$s.Arguments=" + ps('"' + str(target) + '" run') + ";"
               "$s.WorkingDirectory=" + ps(HOME) + ";$s.Description='Seizo simulation-only monitor';$s.Save()")
    subprocess.run(['powershell', '-NoProfile', '-Command', command],
                   check=True, shell=False,
                   creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    # Keep the login bridge entirely silent; status/error reports are files.
    subprocess.Popen([str(python), str(target), 'run'], cwd=HOME, shell=False,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    print('INSTALLED. Auto-starts at Windows sign-in; current Seizo run was not restarted.')
    print('Phone report: https://github.com/' + REPO + '/tree/' + BRANCH)
    print('Remote training:', 'up to 20 per request / 100 per UTC day' if allow_training else 'disabled')
    print('Disable: run this script with disable. No passwords or keys should be pasted into chat.')


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('install', 'run', 'once', 'disable', 'status'))
    p.add_argument('--allow-training', action='store_true', help='Explicit local opt-in: 20 episodes per command, 100/day')
    args = p.parse_args()
    if args.mode == 'install': install(args.allow_training)
    elif args.mode == 'status': print(dump(load(HOME / 'local_status.json', load(HOME / 'bridge_error.json', {}))))
    elif args.mode == 'disable':
        HOME.mkdir(parents=True, exist_ok=True); (HOME / 'DISABLED').write_text('stop')
        startup = Path(os.environ.get('APPDATA', str(HOME))) / 'Microsoft/Windows/Start Menu/Programs/Startup'
        (startup / 'Seizo Simulation Bridge.lnk').unlink(missing_ok=True)
        print('Bridge disabled. Seizo training itself was not stopped.')
    else: main_loop(once=args.mode == 'once')


if __name__ == '__main__':
    try: cli()
    except (Blocked, subprocess.SubprocessError) as e:
        print('SETUP BLOCKED:', str(e) if isinstance(e, Blocked) else type(e).__name__)
        raise SystemExit(2)
