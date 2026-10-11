"""Local JSON bridge between Spectrum (TypeScript) and CSV/Pandas (Python).

Run from the repo root: python backend/pantrypulse_service.py
Defaults to 127.0.0.1:8765; do NOT expose this unauthenticated service to the internet.
"""
from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pantrypulse_engine import PantryPulse
from pantrypulse_gemini import should_interpret, parse_donation

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
                    if should_interpret(app, args["handle"], args["text"]):
                        try:
                            parsed = parse_donation(args["text"])
                            app.on_parsed_intake(
                                handle=args["handle"], space_id=args["space_id"],
                                message_id=args["message_id"], items=parsed.items,
                                zip_code=parsed.zip_code, window=parsed.window,
                                packaging_verified=parsed.packaging_verified,
                            )
                        except Exception as exc:
                            # Keep Gemini failures from crashing the iMessage listener.
                            # Don't expose model credentials or SDK errors to testers.
                            print("Gemini donation intake failed:", type(exc).__name__, str(exc)[:300])
                            p = app.part(args["handle"], args["space_id"])
                            app.notify(p["handle"],
                                "I couldn't interpret that donation. Please text DONATE "
                                "to enter item, quantity, ZIP and delivery time step by step.")
                            key = f"{args['space_id']}|{args['message_id']}"
                            if not app.lookup("inbox", message_key=key):
                                app.tables["inbox"].append({"message_key": key})
                            app.save()
                    else:
                        # A donor saying "I have beans" omitted quantity.
                        # Avoid a model that must output a number inventing one;
                        # begin the explicit missing-field intake instead.
                        p = app.lookup("participants", handle=args["handle"])
                        message_text = args["text"].strip()
                        if (p and p["role"] in ("donor", "pantry")
                                and not p["step"] and not re.search(r"\d", message_text)
                                and re.search(r"\b(?:donat\w*|have|offer\w*|give)\b", message_text, re.I)
                                and re.search(r"\b(?:beans?|cans?|rice|pasta|cereal|tuna|milk|oatmeal|fruit|vegetables)\b", message_text, re.I)):
                            app.on_message(**{**args, "text": "DONATE"})
                        else:
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
