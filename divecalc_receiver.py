"""Bounded HTTP push receiver; handlers never access OBS sources."""

import json
import socket
import threading
from time import monotonic
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from divecalc_adapter import adapt_event_start, adapt_payload

MAX_BODY = 2 * 1024 * 1024
READ_TIMEOUT = 5
REPLAY_TRIGGER_MAX_AGE = 2


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
        if self.path not in (self.server.path, self.server.replay_path):
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
        if self.path != self.server.path:
            with self.server.publish_lock:
                status = self._receive_replay_request(payload)
            self._reply(status)
            return
        with self.server.publish_lock:
            event = payload.get("event")
            event_id = str(event.get("pk", ""))[:100] if isinstance(event, dict) else ""
            def warn(message):
                if not self.server.active:
                    return
                if message in ("Unsupported DiveCalc dives per round", "Unsupported DiveCalc team judge layout"):
                    warning_key = (event_id, message)
                    if warning_key in self.server.warned_team_events:
                        return
                    if len(self.server.warned_team_events) >= 128:
                        self.server.warned_team_events.clear()
                    self.server.warned_team_events.add(warning_key)
                self.server.warn(message)
            updates = adapt_payload(payload, self.server.descriptions, warn)
            event_start = adapt_event_start(payload, warn)
            if event_start is not None:
                updates.append(event_start)
            self.server.mailbox.publish_many(updates, self.server.token)
            if self.server.debug and self.server.active:
                action = payload.get("action")
                if action not in ("dive", "awards", "startlist", "results", "event", "judges"):
                    action = "unknown"
                ignored = (" (countdown only)" if event_start is not None else
                           " (ignored: presentation not supported)") if action in ("event", "judges") else ""
                self.server.log(f"DiveCalc request: action={action}, bytes={len(body)}{ignored}")
        self._reply(200)

    def _receive_replay_request(self, payload):
        if not self.server.active or self.path != self.server.replay_path:
            return 404
        if payload.get("action") != "judges":
            self.server.warn("DiveCalc replay endpoint expects the Present Judges action.")
            return 400
        now = monotonic()
        previous = self.server.last_replay_request
        accepted = previous is None or now - previous >= self.server.replay_cooldown
        if accepted:
            self.server.last_replay_request = now
            self.server.pending_replay_request = now
        if self.server.debug:
            result = "accepted" if accepted else "ignored during cooldown"
            self.server.log(f"DiveCalc replay request: {result}")
        return 200

    def _other_method(self):
        self._reply(self._check() or 405)


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
        self.server.replay_path = None
        self.server.replay_cooldown = 0
        self.server.last_replay_request = None
        self.server.pending_replay_request = None
        # Cleared under publish_lock by stop() so handlers cannot log into an unloaded script.
        self.server.active = True
        self.server.warned_team_events = set()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def configure_replay(self, path: str | None, cooldown: int = 0):
        if path is not None:
            if not path.startswith("/") or "?" in path or "#" in path:
                raise ValueError("replay path must start with / and contain no query or fragment")
            if path == self.server.path:
                raise ValueError("replay path must differ from the main DiveCalc HTTP path")
            if not 1 <= cooldown <= 60:
                raise ValueError("replay cooldown must be between 1 and 60 seconds")
        with self.server.publish_lock:
            if self.server.replay_path != path:
                self.server.pending_replay_request = None
            self.server.replay_path = path
            self.server.replay_cooldown = cooldown

    def take_replay_request(self) -> bool:
        with self.server.publish_lock:
            pending = self.server.pending_replay_request
            self.server.pending_replay_request = None
            # Never start a replay late if the macro was paused or not running.
            return (self.server.active and pending is not None
                    and monotonic() - pending < REPLAY_TRIGGER_MAX_AGE)

    def stop(self):
        with self.server.publish_lock:
            self.server.active = False
            self.server.pending_replay_request = None
        self.server.mailbox.new_token()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)