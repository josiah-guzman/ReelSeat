"""ReelSeat mock API server (Python standard library only).

Run:  python server.py
Open: http://localhost:8000
"""
import json
import logging
import re
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
PORT = 8000

# ---------- Logging ----------
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"


class RecentLogs(logging.Handler):
    """Keeps the last 200 log lines in memory so /api/logs can serve them."""
    def __init__(self):
        super().__init__()
        self.lines = deque(maxlen=200)

    def emit(self, record):
        self.lines.append(self.format(record))


recent = RecentLogs()
recent.setFormatter(logging.Formatter(LOG_FORMAT))

# Preload existing log lines (e.g. the starter mock logs) so /api/logs has history
_existing = LOG_DIR / "reelseat.log"
if _existing.exists():
    recent.lines.extend(_existing.read_text().splitlines()[-200:])

file_handler = RotatingFileHandler(LOG_DIR / "reelseat.log", maxBytes=500_000, backupCount=3)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

log = logging.getLogger("reelseat")
log.setLevel(logging.INFO)
log.addHandler(file_handler)
log.addHandler(console_handler)
log.addHandler(recent)

DB = json.loads((BASE / "data.json").read_text())
log.info("Loaded data.json: %s", ", ".join(f"{k}={len(v)}" for k, v in DB.items()))


def by_id(collection, item_id):
    return next((x for x in DB[collection] if x["id"] == item_id), None)


def get_showtimes(q):
    items = DB["showtimes"]
    for key in ("movieId", "theaterId", "screenId"):
        if key in q:
            items = [s for s in items if s[key] == q[key][0]]
    if "date" in q:
        items = [s for s in items if s["startTime"].startswith(q["date"][0])]
    # attach movie title / theater name so the client needs fewer round trips
    return [
        {**s,
         "movieTitle": by_id("movies", s["movieId"])["title"],
         "theaterName": by_id("theaters", s["theaterId"])["name"]}
        for s in sorted(items, key=lambda s: s["startTime"])
    ]


def get_movie(movie_id):
    movie = by_id("movies", movie_id)
    if not movie:
        return None
    reviews = [r for r in DB["reviews"] if r["movieId"] == movie_id]
    return {**movie, "reviews": reviews}


ROUTES = [
    (r"^/api/theaters$",            lambda m, q: DB["theaters"]),
    (r"^/api/theaters/([\w-]+)$",   lambda m, q: by_id("theaters", m.group(1))),
    (r"^/api/movies$",              lambda m, q: DB["movies"]),
    (r"^/api/movies/([\w-]+)$",     lambda m, q: get_movie(m.group(1))),
    (r"^/api/showtimes$",           lambda m, q: get_showtimes(q)),
    (r"^/api/reviews$",             lambda m, q: DB["reviews"]),
    (r"^/api/parties$",             lambda m, q: DB["parties"]),
    (r"^/api/logs$",                lambda m, q: list(recent.lines)[-int(q.get("limit", ["50"])[0]):]),
]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json"):
        self._status = status
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")  # allow other front ends
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        start = time.perf_counter()
        self._status = 500
        try:
            self._route()
        except Exception:
            log.exception("Unhandled error on %s", self.path)
            self._send(500, {"error": "Internal server error"})
        finally:
            ms = (time.perf_counter() - start) * 1000
            level = logging.WARNING if self._status >= 400 else logging.INFO
            if self.path.startswith("/api/logs"):
                level = logging.DEBUG  # don't let the log viewer flood the log
            log.log(level, "%s GET %s -> %d (%.1f ms)", self.client_address[0], self.path, self._status, ms)

    def _route(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path in ("/", "/index.html"):
            return self._send(200, (BASE / "index.html").read_bytes(), "text/html")

        for pattern, handler in ROUTES:
            m = re.match(pattern, url.path)
            if m:
                result = handler(m, query)
                if result is None:
                    return self._send(404, {"error": "Not found"})
                return self._send(200, result)

        self._send(404, {"error": "Unknown route"})

    def log_message(self, fmt, *args):
        pass  # replaced by our own request logging in do_GET


if __name__ == "__main__":
    log.info("ReelSeat API starting on http://localhost:%d", PORT)
    try:
        HTTPServer(("", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped by user")
