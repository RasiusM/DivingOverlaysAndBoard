"""Capture DiveCalc HTTP result feeds without changing OBS or competition data."""

import argparse
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading


MAX_BODY_BYTES = 2 * 1024 * 1024
CAPTURE_LOCK = threading.Lock()


class FeedProbeHandler(BaseHTTPRequestHandler):
    capture_path = Path(tempfile.gettempdir()) / "divecalc-feed-capture.jsonl"

    def read_body(self):
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if transfer_encoding == "chunked":
            body = bytearray()
            while True:
                chunk_size = int(self.rfile.readline(128).split(b";", 1)[0], 16)
                if chunk_size < 0 or len(body) + chunk_size > MAX_BODY_BYTES:
                    raise ValueError("Invalid or oversized chunk")
                if chunk_size == 0:
                    while True:
                        trailer = self.rfile.readline(8192)
                        if trailer in (b"\r\n", b"\n"):
                            return bytes(body)
                        if not trailer:
                            raise ValueError("Incomplete chunk trailers")
                chunk = self.rfile.read(chunk_size)
                if len(chunk) != chunk_size or self.rfile.read(2) != b"\r\n":
                    raise ValueError("Incomplete chunk")
                body.extend(chunk)
        if transfer_encoding:
            raise ValueError("Unsupported Transfer-Encoding")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= MAX_BODY_BYTES:
            raise ValueError("Invalid or oversized Content-Length")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("Incomplete request body")
        return body

    def capture(self):
        self.connection.settimeout(5)
        try:
            body = self.read_body()
        except (ValueError, OSError) as error:
            print(f"Request rejected: {error}", flush=True)
            self.send_error(400, "Invalid or incomplete request body")
            return

        text = body.decode("utf-8-sig", errors="replace")
        try:
            payload = json.loads(text)
            parse_error = None
        except ValueError as error:
            payload = None
            parse_error = str(error)

        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "client": self.client_address[0],
            "method": self.command,
            "path": self.path,
            "headers": [
                [name, "[redacted]" if name.lower() in
                 ("authorization", "cookie", "proxy-authorization") else value]
                for name, value in self.headers.items()
            ],
            "body_text": text,
            "body_base64": base64.b64encode(body).decode("ascii"),
            "json": payload,
            "json_error": parse_error,
        }
        try:
            with CAPTURE_LOCK:
                with self.capture_path.open("a", encoding="utf-8") as capture_file:
                    capture_file.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError as error:
            print(f"Capture failed: {error}", flush=True)
            self.send_error(500, "Could not save capture")
            return

        action = payload.get("action", "unknown") if isinstance(payload, dict) else "non-object JSON"
        print(
            f"{record['received_at']} {self.command} {self.path} "
            f"bytes={len(body)} action={action} json_valid={parse_error is None}",
            flush=True,
        )
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = capture
    do_PUT = capture
    do_PATCH = capture
    do_GET = capture

    def log_message(self, format_string, *args):
        print(format_string % args, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=FeedProbeHandler.capture_path)
    arguments = parser.parse_args()
    FeedProbeHandler.capture_path = arguments.log
    with ThreadingHTTPServer(("127.0.0.1", arguments.port), FeedProbeHandler) as server:
        print(f"Listening: http://127.0.0.1:{server.server_port}/divecalc", flush=True)
        print(f"Capture log: {arguments.log}", flush=True)
        print("Loopback only. Captures contain competition data. Ctrl+C stops the receiver.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()