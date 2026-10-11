"""Local JSON bridge between Spectrum (TypeScript) and CSV/Pandas (Python).

Run from the repo root: python backend/pantrypulse_service.py
Defaults to 127.0.0.1:8765; do NOT expose this unauthenticated service to the internet.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pantrypulse_engine import PantryPulse

DATA_DIR = Path(__file__).resolve().parent / "data"
app = PantryPulse(DATA_DIR)
lock = threading.RLock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[PantryPulse] " + fmt % args)

    def respond(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n < 0 or n > 1_000_000:
            raise ValueError("Invalid payload length")
        return json.loads(self.rfile.read(n))

    def do_GET(self):
        try:
            with lock:
                if self.path == "/health":
                    return self.respond({"ok": True, "pantries_registered": len([p for p in app.tables["participants"] if p["pantry_id"]])})
                if self.path == "/pending":
                    return self.respond({"messages": [dict(item, space_id=app.recipient_space(item["recipient"])) for item in app.pending()]})
                return self.respond({"error": "not found"}, 404)
        except Exception as exc:
            print("GET error:", repr(exc))
            self.respond({"error": str(exc)}, 500)

    def do_POST(self):
        try:
            payload = self.read_json()
            with lock:
                if self.path == "/message":
                    for field in ("handle", "space_id", "message_id", "text"):
                        if not isinstance(payload.get(field), str) or not payload[field]:
                            raise ValueError(f"Missing {field}")
                    args = {k: payload[k] for k in ("handle", "space_id", "message_id", "text")}
                    if app.lookup("inbox", message_key=f"{args['space_id']}|{args['message_id']}"):
                        return self.respond({"ok": True})
                    app.on_message(**args)
                    return self.respond({"ok": True})
                if self.path == "/parsed":
                    for field in ("handle", "space_id", "message_id", "items"):
                        if field not in payload: raise ValueError(f"Missing {field}")
                    if not isinstance(payload["items"], list) or len(payload["items"]) > 20:
                        raise ValueError("items must be a list of at most 20 donations")
                    app.from_gemini(**{k: payload[k] for k in ("handle", "space_id", "message_id", "items")})
                    return self.respond({"ok": True})
                if self.path == "/ack":
                    app.ack(str(payload.get("id", "")))
                    return self.respond({"ok": True})
                return self.respond({"error": "not found"}, 404)
        except (ValueError, TypeError, KeyError) as exc:
            return self.respond({"error": str(exc)}, 400)
        except Exception as exc:
            print("POST error:", repr(exc))
            return self.respond({"error": str(exc)}, 500)


if __name__ == "__main__":
    port = int(os.getenv("PANTRYPULSE_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PantryPulse Python service running at http://127.0.0.1:{port}")
    print("Using existing demo CSV inventory. This is NOT a real pantry network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
