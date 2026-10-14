#!/usr/bin/env python3
"""Private Railway hosting entrypoint for the offline Seizo simulator.

This deliberately does NOT expose any Pi, motor, GPIO, or camera endpoints.
Requires a Basic-Auth password stored in Railway Variables.
"""
from __future__ import annotations
import base64
import binascii
import hmac
import json
import os
import pathlib
import secrets
import signal
import sys
import threading
from urllib.parse import urlsplit

APP_DIR = pathlib.Path(__file__).resolve().parent / 'Seizo_Learn'
sys.path.insert(0,str(APP_DIR))
from app import make_handler, Server
from core.runner import Runner
from core.cloud import HackClubPlanner

PASSWORD=os.environ.get('SEIZO_WEB_PASSWORD','')
USERNAME=os.environ.get('SEIZO_WEB_USERNAME','seizo')
DATA_DIR=pathlib.Path(os.environ.get('SEIZO_DATA_DIR','/data'))
ALLOWED_HOSTS={s.strip().lower() for s in os.environ.get('SEIZO_ALLOWED_HOSTS','').split(',') if s.strip()}
if os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
    ALLOWED_HOSTS.add(os.environ['RAILWAY_PUBLIC_DOMAIN'].lower().strip())


def make_protected_handler(runner,cloud,port):
    token=secrets.token_urlsafe(32)
    stop=threading.Event()
    base=make_handler(runner,token,stop,cloud,'seizo-railway-private')

    class PrivateHandler(base):
        def host_ok(self):
            host=self.headers.get('Host','').strip().lower().split(':',1)[0]
            if host in ALLOWED_HOSTS:
                return True
            # Localhost allowed for private health/automated smoke testing.
            return host in ('127.0.0.1','localhost') and self.client_address[0] in ('127.0.0.1','::1')

        def local(self):
            return self.host_ok()

        def expected_origin(self):
            host=self.headers.get('Host','')
            name=host.split(':',1)[0].lower()
            scheme='http' if name in ('127.0.0.1','localhost') else 'https'
            return scheme+'://'+host

        def authorized(self):
            raw=self.headers.get('Authorization','')
            if not raw.startswith('Basic '):
                return False
            try:
                decoded=base64.b64decode(raw[6:].strip(),validate=True).decode('utf-8')
                username,passwd=decoded.split(':',1)
            except (ValueError,UnicodeDecodeError,binascii.Error):
                return False
            return hmac.compare_digest(username,USERNAME) and hmac.compare_digest(passwd,PASSWORD)

        def reject(self):
            msg=b'Seizo is private. Use the password from your Railway service Variables.'
            self.send_response(401)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('WWW-Authenticate','Basic realm="Seizo Private"')
            self.send_header('Content-Length',str(len(msg)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(msg)

        def do_GET(self):
            if urlsplit(self.path).path=='/healthz':
                # HTTP health checks don't reveal the app or any data.
                response=b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            if not self.host_ok():
                self.send(403,{'error':'Unrecognized host'})
                return
            if not self.authorized():
                self.reject()
                return
            return super().do_GET()

        def do_POST(self):
            if not self.host_ok():
                self.send(403,{'error':'Unrecognized host'})
                return
            if not self.authorized():
                self.reject()
                return
            if urlsplit(self.path).path=='/api/quit':
                return self.send(400,{'error':'Hosted Seizo stays online. Use Stop & Save to pause training.'})
            return super().do_POST()

    return PrivateHandler


def main():
    if len(PASSWORD)<16:
        raise SystemExit('SEIZO_WEB_PASSWORD required; set a 16+ character secret in Railway Variables.')
    port=int(os.environ.get('PORT','8080'))
    if not 0<port<65536:raise SystemExit('Invalid PORT')
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    runner=Runner(DATA_DIR)
    # This service has no hardware IO. Credentials are optional, never written to image.
    cloud=HackClubPlanner(api_key=os.environ.get('HACKCLUB_API_KEY',''))
    server=Server(('0.0.0.0',port),make_protected_handler(runner,cloud,port))
    print('Seizo private simulator ready on port',port,'data in',DATA_DIR,flush=True)
    print('Physical controller: DISCONNECTED. Current contact physics remains approximate.',flush=True)
    def request_stop(*_):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,request_stop)
    signal.signal(signal.SIGINT,request_stop)
    try:server.serve_forever(poll_interval=0.3)
    finally:
        try:runner.shutdown()
        finally:server.server_close()

if __name__=='__main__':
    main()