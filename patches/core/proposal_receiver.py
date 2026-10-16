"""Loopback mock Pi. Receipt-only HTTP, no execution route or device imports."""
from __future__ import annotations
import http.client
import http.server
import threading
from .proposal_protocol import (MAX_BODY, ReceiptStore, Rejected, canonical,
                                require, sha256, sign, strict_json)


def handler_for(store):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            raw = canonical(value)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Seizo-Receipt', sign(store.key, raw))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.reply(404, {'error': 'no_read_or_execution_route'})

        def do_POST(self):
            try:
                require(self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}', 'invalid_host')
                require(self.headers.get('Origin') is None, 'browser_origin_not_allowed')
                require(self.path == '/v1/proposals', 'no_execution_route')
                require(self.headers.get('Content-Type') == 'application/json', 'json_required')
                require(self.headers.get('Transfer-Encoding') is None, 'chunked_body_not_allowed')
                lengths = self.headers.get_all('Content-Length', [])
                require(len(lengths) == 1 and lengths[0].isdigit(), 'invalid_body_length')
                n = int(lengths[0])
                require(0 < n <= MAX_BODY, 'body_too_large')
                self.connection.settimeout(2.)
                raw = self.rfile.read(n)
                require(len(raw) == n, 'incomplete_body')
                result = store.receive(raw, self.headers.get('X-Seizo-Proposal', ''))
                self.reply(200, result)
            except Rejected as exc:
                self.reply(400, {'error': exc.code, 'automatic_motion_enabled': False})
            except (OSError, ValueError):
                self.reply(400, {'error': 'invalid_or_interrupted_request', 'automatic_motion_enabled': False})
    return Handler


class MockPiTransport:
    """A real local HTTP round trip, explicitly NOT a connection to a real Pi."""
    def __init__(self, expected):
        self.store = ReceiptStore(expected)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()

    @property
    def session_id(self):
        return self.store.session_id

    def stop(self):
        self.store.stop()

    def send(self, proposal):
        raw = canonical(proposal)
        require(not self.store.stopped.is_set(), 'stopped')
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3.)
        try:
            # Exactly one attempt. Never retry an uncertain receipt.
            conn.request('POST', '/v1/proposals', body=raw,
                         headers={'Content-Type': 'application/json',
                                  'X-Seizo-Proposal': sign(self.store.key, raw)})
            response = conn.getresponse()
            data = response.read(MAX_BODY + 1)
            import hmac
            require(len(data) <= MAX_BODY and hmac.compare_digest(
                sign(self.store.key, data), response.getheader('X-Seizo-Receipt', '')),
                'untrusted_receipt')
            value = strict_json(data)
            require(not self.store.stopped.is_set(), 'stopped')
            if response.status != 200:
                raise Rejected(value.get('error', 'proposal_rejected'))
            require(value.get('schema') == 'seizo-proposal-receipt/v1'
                    and value.get('proposal_id') == proposal['proposal_id']
                    and value.get('session_id') == self.session_id
                    and value.get('proposal_sha256') == sha256(raw)
                    and value.get('state') == 'received_by_mock_pi'
                    and all(value.get(k) is False for k in (
                        'automatic_motion_enabled', 'authorized', 'executed', 'physically_verified')),
                    'receipt_mismatch')
            return value
        except (OSError, http.client.HTTPException):
            self.stop()
            raise Rejected('connection_lost_no_retry') from None
        finally:
            conn.close()

    def close(self):
        self.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1.)
