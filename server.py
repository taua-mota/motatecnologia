#!/usr/bin/env python3
import base64
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ANALYTICS_DB_PATH", ROOT_DIR / "data" / "analytics.db"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
ANALYTICS_USERNAME = os.environ.get("ANALYTICS_USERNAME", "").strip()
ANALYTICS_PASSWORD = os.environ.get("ANALYTICS_PASSWORD", "").strip()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at INTEGER NOT NULL,
              event_type TEXT NOT NULL,
              event_name TEXT NOT NULL,
              page TEXT NOT NULL,
              referrer TEXT NOT NULL,
              session_id TEXT NOT NULL,
              ip TEXT NOT NULL,
              user_agent TEXT NOT NULL,
              language TEXT NOT NULL,
              timezone TEXT NOT NULL,
              viewport TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_created_at ON visits(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_event_type ON visits(event_type);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_page ON visits(page);")


def sanitize(value: str | None, limit: int) -> str:
    if not value:
        return ""
    return value.strip()[:limit]


def get_client_ip(handler: SimpleHTTPRequestHandler) -> str:
    xff = sanitize(handler.headers.get("X-Forwarded-For"), 200)
    if xff:
        return xff.split(",")[0].strip()[:64]

    real_ip = sanitize(handler.headers.get("X-Real-IP"), 64)
    if real_ip:
        return real_ip

    return sanitize(handler.client_address[0], 64)


def insert_visit(payload: dict, ip: str, user_agent: str) -> None:
    now_ms = int(time.time() * 1000)
    event_type = sanitize(payload.get("eventType"), 20).lower() or "event"
    if event_type not in ("pageview", "event"):
        event_type = "event"

    event_name = sanitize(payload.get("eventName"), 120) or event_type
    page = sanitize(payload.get("page"), 255) or "/"

    referrer = sanitize(payload.get("referrer"), 500)
    session_id = sanitize(payload.get("sessionId"), 120)
    language = sanitize(payload.get("language"), 40)
    timezone_name = sanitize(payload.get("timezone"), 80)
    viewport = sanitize(payload.get("viewport"), 40)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO visits (
              created_at, event_type, event_name, page, referrer, session_id,
              ip, user_agent, language, timezone, viewport
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_ms,
                event_type,
                event_name,
                page,
                referrer,
                session_id,
                ip,
                user_agent,
                language,
                timezone_name,
                viewport,
            ),
        )


def get_stats() -> dict:
    now_ms = int(time.time() * 1000)
    one_day_ago_ms = now_ms - (24 * 60 * 60 * 1000)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        total_events = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        total_pageviews = conn.execute(
            "SELECT COUNT(*) FROM visits WHERE event_type = 'pageview'"
        ).fetchone()[0]
        unique_visitors = conn.execute(
            """
            SELECT COUNT(DISTINCT CASE
              WHEN session_id <> '' THEN session_id
              ELSE ip
            END) FROM visits WHERE event_type = 'pageview'
            """
        ).fetchone()[0]
        last_24h = conn.execute(
            "SELECT COUNT(*) FROM visits WHERE event_type = 'pageview' AND created_at >= ?",
            (one_day_ago_ms,),
        ).fetchone()[0]

        top_pages_rows = conn.execute(
            """
            SELECT page, COUNT(*) AS hits
            FROM visits
            WHERE event_type = 'pageview'
            GROUP BY page
            ORDER BY hits DESC
            LIMIT 10
            """
        ).fetchall()

        top_ref_rows = conn.execute(
            """
            SELECT referrer, COUNT(*) AS hits
            FROM visits
            WHERE referrer <> ''
            GROUP BY referrer
            ORDER BY hits DESC
            LIMIT 10
            """
        ).fetchall()

        top_event_rows = conn.execute(
            """
            SELECT event_name, COUNT(*) AS hits
            FROM visits
            WHERE event_type = 'event'
            GROUP BY event_name
            ORDER BY hits DESC
            LIMIT 10
            """
        ).fetchall()

        recent_rows = conn.execute(
            """
            SELECT created_at, event_type, event_name, page, referrer, ip, language, timezone, viewport, user_agent
            FROM visits
            ORDER BY created_at DESC
            LIMIT 100
            """
        ).fetchall()

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "pageviews": total_pageviews,
            "uniqueVisitors": unique_visitors,
            "events": total_events,
            "last24hPageviews": last_24h,
        },
        "topPages": [{"page": row["page"], "hits": row["hits"]} for row in top_pages_rows],
        "topReferrers": [
            {"referrer": row["referrer"], "hits": row["hits"]} for row in top_ref_rows
        ],
        "topEvents": [{"eventName": row["event_name"], "hits": row["hits"]} for row in top_event_rows],
        "recent": [
            {
                "createdAt": row["created_at"],
                "eventType": row["event_type"],
                "eventName": row["event_name"],
                "page": row["page"],
                "referrer": row["referrer"],
                "ip": row["ip"],
                "language": row["language"],
                "timezone": row["timezone"],
                "viewport": row["viewport"],
                "userAgent": row["user_agent"],
            }
            for row in recent_rows
        ],
    }


def auth_configured() -> bool:
    return bool(ANALYTICS_USERNAME and ANALYTICS_PASSWORD)


def has_basic_auth(handler: SimpleHTTPRequestHandler) -> bool:
    if not auth_configured():
        return False

    auth_header = sanitize(handler.headers.get("Authorization"), 1024)
    if not auth_header.startswith("Basic "):
        return False

    token = auth_header.removeprefix("Basic ").strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return False

    if ":" not in decoded:
        return False

    username, password = decoded.split(":", 1)
    return username == ANALYTICS_USERNAME and password == ANALYTICS_PASSWORD


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_auth_required(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED.value)
        self.send_header("WWW-Authenticate", 'Basic realm="Analytics Dashboard"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            json.dumps({"error": "Autenticação obrigatória"}).encode("utf-8")
        )

    def _send_security_not_configured(self) -> None:
        self._send_json(
            {
                "error": (
                    "Analytics desabilitado: configure ANALYTICS_USERNAME e "
                    "ANALYTICS_PASSWORD."
                )
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _serve_dashboard(self) -> None:
        file_path = ROOT_DIR / "dashboard.html"
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND.value, "Dashboard não encontrado")
            return

        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/track":
            self.send_error(HTTPStatus.NOT_FOUND.value, "Endpoint não encontrado")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 10_000:
            self.send_error(HTTPStatus.BAD_REQUEST.value, "Payload inválido")
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload deve ser objeto")
        except Exception:
            self.send_error(HTTPStatus.BAD_REQUEST.value, "JSON inválido")
            return

        ip = get_client_ip(self)
        user_agent = sanitize(self.headers.get("User-Agent"), 500)

        insert_visit(payload, ip, user_agent)
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        sensitive_prefixes = ("/data", "/.git", "/.codex", "/__pycache__")
        sensitive_files = {
            "/server.py",
            "/dashboard.html",
            "/README.md",
            "/.env",
            "/.impeccable.md",
            "/.gitignore",
        }

        if (
            path.startswith(sensitive_prefixes)
            or path in sensitive_files
            or path.endswith((".db", ".sqlite", ".sqlite3"))
        ):
            self.send_error(HTTPStatus.NOT_FOUND.value, "Recurso não encontrado")
            return

        if path == "/health":
            self._send_json({"status": "ok"})
            return

        if path == "/api/stats":
            if not auth_configured():
                self._send_security_not_configured()
                return

            if not has_basic_auth(self):
                self._send_auth_required()
                return

            self._send_json(get_stats())
            return

        if path in ("/dashboard", "/dashboard/"):
            if not auth_configured():
                self._send_security_not_configured()
                return

            if not has_basic_auth(self):
                self._send_auth_required()
                return

            self._serve_dashboard()
            return

        super().do_GET()


def main() -> None:
    init_db()
    if not auth_configured():
        print(
            "WARNING: ANALYTICS_USERNAME/ANALYTICS_PASSWORD não definidos. "
            "Dashboard e /api/stats ficarão desabilitados."
        )

    httpd = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Analytics server running on http://{HOST}:{PORT} | DB: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
