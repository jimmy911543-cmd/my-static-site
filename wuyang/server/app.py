#!/usr/bin/env python3
"""五楊不動產事務所：靜態網站、聯絡資料與專屬登入。"""

import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "inquiries.db"
SECRET_PATH = DATA / "secret.key"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
PASSWORD = os.environ.get("WUYANG_ADMIN_PASSWORD", "wuyang")
SESSION_SECONDS = 12 * 60 * 60
MAX_BODY = 32_000
TAIPEI = ZoneInfo("Asia/Taipei")
BLOCKED = {"data", "server", "deploy"}
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}
FAILURES = {}


def secret() -> bytes:
    DATA.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_bytes(os.urandom(32))
        try:
            os.chmod(SECRET_PATH, 0o600)
        except OSError:
            pass
    return SECRET_PATH.read_bytes()


def db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            tel TEXT NOT NULL DEFAULT '',
            mobile TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL
        )
        """
    )
    return conn


def password_ok(given: str) -> bool:
    left = hashlib.sha256(given.encode("utf-8")).digest()
    right = hashlib.sha256(PASSWORD.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


def make_token() -> str:
    expiry = str(int(time.time()) + SESSION_SECONDS)
    sig = hmac.new(secret(), expiry.encode("ascii"), hashlib.sha256).hexdigest()
    return expiry + "." + sig


def token_ok(token: str) -> bool:
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False
    expiry, sig = parts
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    expected = hmac.new(secret(), expiry.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def limited(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in FAILURES.get(ip, []) if now - stamp < 600]
    FAILURES[ip] = recent
    return len(recent) >= 8


class App(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            if key == name:
                return unquote(value)
        return ""

    def logged_in(self) -> bool:
        return token_ok(self.cookie("wuyang_session"))

    def send_json(self, status: int, payload: dict, cookie: str = "", clear: bool = False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie or clear:
            secure = self.headers.get("X-Forwarded-Proto", "http") == "https"
            pieces = [
                "wuyang_session=" + ("" if clear else cookie),
                "HttpOnly",
                "SameSite=Strict",
                "Path=/",
                "Max-Age=" + ("0" if clear else str(SESSION_SECONDS)),
            ]
            if secure:
                pieces.append("Secure")
            self.send_header("Set-Cookie", "; ".join(pieces))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > MAX_BODY:
            raise ValueError("too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(200, {"ok": True})
            return
        if path == "/api/session":
            self.send_json(200, {"ok": self.logged_in()})
            return
        if path == "/api/inquiries":
            if not self.logged_in():
                self.send_json(401, {"error": "請先登入"})
                return
            with db() as conn:
                rows = conn.execute(
                    "SELECT created_at, name, tel, mobile, email, message FROM inquiries ORDER BY id DESC"
                ).fetchall()
            self.send_json(200, {"items": [dict(row) for row in rows]})
            return
        self.serve_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "資料格式不正確"})
            return
        if path == "/api/login":
            self.login(payload)
            return
        if path == "/api/logout":
            self.send_json(200, {"ok": True}, clear=True)
            return
        if path == "/api/contact":
            self.save_contact(payload)
            return
        self.send_json(404, {"error": "找不到"})

    def login(self, payload: dict):
        ip = self.client_ip()
        if limited(ip):
            self.send_json(429, {"error": "嘗試次數過多，請稍後再登入"})
            return
        given = str(payload.get("password") or "")
        if not password_ok(given):
            FAILURES.setdefault(ip, []).append(time.time())
            self.send_json(401, {"error": "密碼不正確"})
            return
        FAILURES.pop(ip, None)
        self.send_json(200, {"ok": True}, cookie=make_token())

    def save_contact(self, payload: dict):
        if str(payload.get("website") or "").strip():
            self.send_json(200, {"ok": True})
            return
        name = str(payload.get("name") or "").strip()
        tel = str(payload.get("tel") or "").strip()
        mobile = str(payload.get("mobile") or "").strip()
        email = str(payload.get("email") or "").strip()
        message = str(payload.get("message") or "").strip()
        if not name:
            self.send_json(400, {"error": "請填寫客戶名稱"})
            return
        if not mobile:
            self.send_json(400, {"error": "請填寫手機"})
            return
        if not message:
            self.send_json(400, {"error": "請填寫您想了解的事情"})
            return
        if email and "@" not in email:
            self.send_json(400, {"error": "信箱格式不正確"})
            return
        if max(len(name), len(tel), len(mobile), len(email)) > 120 or len(message) > 4000:
            self.send_json(400, {"error": "內容過長"})
            return
        created = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
        with db() as conn:
            conn.execute(
                "INSERT INTO inquiries (created_at, name, tel, mobile, email, message) VALUES (?, ?, ?, ?, ?, ?)",
                (created, name, tel, mobile, email, message),
            )
        self.send_json(200, {"ok": True})

    def serve_file(self, path: str):
        relative = unquote(path).lstrip("/")
        if relative == "":
            relative = "index.html"
        candidate = (ROOT / relative).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            self.send_error(404)
            return
        first = relative.split("/", 1)[0]
        if first in BLOCKED or first.startswith("."):
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        content = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(candidate.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)


def main():
    db().close()
    server = ThreadingHTTPServer((HOST, PORT), App)
    print("五楊網站服務於 http://%s:%s" % (HOST, PORT))
    server.serve_forever()


if __name__ == "__main__":
    main()
