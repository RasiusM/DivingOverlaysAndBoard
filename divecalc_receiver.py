"""Bounded HTTP push receiver; handlers never access OBS sources."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from divecalc_adapter import adapt_payload

MAX_BODY = 2 * 1024 * 1024
READ_TIMEOUT = 5


class BodyError(Exception):
    def __init__(self, status):
        self.status = status


class ReceiverServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(READ_TIMEOUT)

    def log_message(self, format, *args):
        pass

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._other_method
        raise AttributeError(name)

    def _reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _read_exact(self, size):
        data = self.rfile.read(size)
        if len(data) != size:
            raise BodyError(400)
        return data

    def _read_body(self):
        transfer = self.headers.get_all("Transfer-Encoding", [])
        lengths = self.headers.get_all("Content-Length", [])
        if transfer:
            if len(transfer) != 1 or transfer[0].lower().strip() != "chunked" or lengths:
                raise BodyError(400)
            chunks = []
            total = 0
            while True:
                line = self.rfile.readline(1025)
                if len(line) > 1024 or not line.endswith(b"\r\n"):
                    raise BodyError(400)
                try:
                    size = int(line[:-2].split(b";", 1)[0], 16)
                except ValueError:
                    raise BodyError(400)
                if size < 0:
                    raise BodyError(400)
                if size == 0:
                    trailer_size = 0
                    while True:
                        trailer = self.rfile.readline(1025)
                        trailer_size += len(trailer)
                        if not trailer.endswith(b"\r\n") or trailer_size > 8192:
                            raise BodyError(400)
                        if trailer == b"\r\n":
                            return b"".join(chunks)
                total += size
                if total > MAX_BODY:
                    raise BodyError(413)
                chunks.append(self._read_exact(size))
                if self._read_exact(2) != b"\r\n":
                    raise BodyError(400)
        if len(lengths) != 1:
            raise BodyError(400)
        try:
            length = int(lengths[0])
        except ValueError:
            raise BodyError(400)
        if length < 0:
            raise BodyError(400)
        if length > MAX_BODY:
            raise BodyError(413)
        return self._read_exact(length)

    def _check(self):
        if self.server.allowed_ip and self.client_address[0] != self.server.allowed_ip:
            return 403
        if self.path != self.server.path:
            return 404
        return None

    def do_POST(self):
        status = self._check()
        if status:
            self._reply(status)
            return
        try:
            body = self._read_body()
            payload = json.loads(body.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
        except BodyError as error:
            self._reply(error.status)
            return
        except (ValueError, UnicodeError, OSError, socket.timeout, RecursionError):
            self._reply(400)
            return
        with self.server.publish_lock:
            event = payload.get("event")
            event_id = str(event.get("pk", ""))[:100] if isinstance(event, dict) else ""
            def warn(message):
                if message in ("Unsupported DiveCalc team event", "Unsupported DiveCalc team judge layout"):
                    warning_key = (event_id, message)
                    if warning_key in self.server.warned_team_events:
                        return
                    if len(self.server.warned_team_events) >= 128:
                        self.server.warned_team_events.clear()
                    self.server.warned_team_events.add(warning_key)
                self.server.warn(message)
            updates = adapt_payload(payload, self.server.descriptions, warn)
            self.server.mailbox.publish_many(updates, self.server.token)
        if self.server.debug:
            action = payload.get("action")
            if action not in ("dive", "awards", "startlist", "results", "event", "judges"):
                action = "unknown"
            self.server.log(f"DiveCalc request: action={action}, bytes={len(body)}")
        self._reply(200)

    def _other_method(self):
        self._reply(self._check() or 405)

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _other_method


class DiveCalcReceiver:
    def __init__(self, mailbox, token, port=8765, path="/divecalc", allowed_ip="", descriptions=None, warn=lambda message: None, log=lambda message: None, debug=False):
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("DiveCalc path must start with / and contain no query or fragment")
        self.server = ReceiverServer(("0.0.0.0", port), Handler)
        self.server.mailbox = mailbox
        self.server.token = token
        self.server.path = path
        self.server.allowed_ip = allowed_ip
        self.server.descriptions = descriptions or {}
        self.server.warn = warn
        self.server.log = log
        self.server.debug = debug
        self.server.publish_lock = threading.Lock()
        self.server.warned_team_events = set()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def stop(self):
        self.server.mailbox.new_token()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)