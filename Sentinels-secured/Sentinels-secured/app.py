from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, send_from_directory, g, abort
from functools import wraps
from datetime import datetime, timedelta
import os
import json
import cv2
import glob
import logging
import time
import secrets
import requests as req

# Security and Database dependencies
from dotenv import load_dotenv
import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__, template_folder="Frontend/html", static_folder="Frontend", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# ── Secure Session Cookie Configuration ─────────────────────────────────────
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # HttpOnly: no JS access to session cookie
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV", "production") == "production",  # Secure flag in prod
    SESSION_COOKIE_SAMESITE="Lax",      # SameSite: CSRF mitigation
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),  # Session timeout: 30 min
)

CCTV_FOLDER = os.path.join(os.path.dirname(__file__), "cctv_footage")
LOG_FILE    = os.path.join(os.path.dirname(__file__), "logs", "access.log")

os.makedirs(CCTV_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", 5432)
    )

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cctv")

def write_log(event: str, user: str = "anonymous", ip: str = ""):
    msg = f"USER={user} | IP={ip} | {event}"
    logger.info(msg)

# ── IP Blacklist ─────────────────────────────────────────────────────────────
IP_BLACKLIST: set = set(
    ip.strip() for ip in os.getenv("IP_BLACKLIST", "").split(",") if ip.strip()
)

def get_client_ip() -> str:
    """Return real client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""

@app.before_request
def block_blacklisted_ips():
    ip = get_client_ip()
    if ip in IP_BLACKLIST:
        write_log("BLOCKED_BLACKLISTED_IP", ip=ip)
        abort(403)

# ── Rate Limiting (in-memory) ─────────────────────────────────────────────────
# Stores {ip: [timestamp, ...]} for login attempts
_rate_limit_store: dict = {}
RATE_LIMIT_MAX    = int(os.getenv("RATE_LIMIT_MAX", 5))       # max attempts
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", 300))  # seconds (5 min)
RATE_LIMIT_BAN    = int(os.getenv("RATE_LIMIT_BAN", 900))     # ban duration (15 min)
_banned_until: dict = {}  # {ip: datetime}

def is_rate_limited(ip: str) -> bool:
    """Return True if ip has exceeded login attempt threshold."""
    now = time.time()
    # Check if currently banned
    if ip in _banned_until:
        if now < _banned_until[ip]:
            return True
        else:
            del _banned_until[ip]
            _rate_limit_store.pop(ip, None)

    # Purge old attempts
    attempts = _rate_limit_store.get(ip, [])
    attempts = [t for t in attempts if now - t < RATE_LIMIT_WINDOW]
    _rate_limit_store[ip] = attempts

    if len(attempts) >= RATE_LIMIT_MAX:
        _banned_until[ip] = now + RATE_LIMIT_BAN
        write_log(f"RATE_LIMIT_BAN duration={RATE_LIMIT_BAN}s", ip=ip)
        return True
    return False

def record_attempt(ip: str):
    now = time.time()
    _rate_limit_store.setdefault(ip, []).append(now)

# ── CSRF Protection ───────────────────────────────────────────────────────────
def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "POST":
            token = (
                request.form.get("csrf_token")
                or request.headers.get("X-CSRFToken")
                or request.headers.get("X-CSRF-Token")
            )
            if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
                write_log("CSRF_REJECTED", ip=get_client_ip())
                abort(403)
        return f(*args, **kwargs)
    return decorated

app.jinja_env.globals["csrf_token"] = generate_csrf_token

# ── Security Headers (CSP, Clickjacking, etc.) ───────────────────────────────
@app.after_request
def set_security_headers(response):
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "          # inline scripts needed for clock/UI
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://db.onlinewebfonts.com; "
        "font-src 'self' https://fonts.gstatic.com https://db.onlinewebfonts.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "                      # Clickjacking protection (modern)
        "object-src 'none';"
    )
    response.headers["Content-Security-Policy"] = csp

    # Clickjacking protection (legacy browsers)
    response.headers["X-Frame-Options"] = "DENY"

    # Other hardening headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(self)"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ── Role-Based Access Control ─────────────────────────────────────────────────
ROLES = {
    "admin":    {"dashboard", "footage", "logs", "cameras"},
    "operator": {"dashboard", "footage", "cameras"},
    "viewer":   {"dashboard"},
}

def role_required(*permissions):
    """Decorator: user must be logged in and have all listed permissions."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            role  = session.get("role", "viewer")
            allowed = ROLES.get(role, set())
            if not all(p in allowed for p in permissions):
                write_log(f"RBAC_DENIED role={role} required={permissions}", session["user"], get_client_ip())
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        # Session timeout: refresh or expire
        last_active = session.get("last_active")
        if last_active:
            elapsed = (datetime.utcnow() - datetime.fromisoformat(last_active)).total_seconds()
            if elapsed > app.config["PERMANENT_SESSION_LIFETIME"].total_seconds():
                session.clear()
                write_log("SESSION_EXPIRED", ip=get_client_ip())
                return redirect(url_for("login"))
        session["last_active"] = datetime.utcnow().isoformat()
        session.modified = True
        return f(*args, **kwargs)
    return decorated

# ── Camera Config ─────────────────────────────────────────────────────────────
CAMERAS = {}
caps    = {}

def get_camera_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "cameras.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            return json.load(f)
    return []

for cam in get_camera_config():
    CAMERAS[cam["id"]] = cam["source"]

def generate_frames(cam_id: int):
    src = CAMERAS.get(cam_id, cam_id)
    if cam_id not in caps or not caps[cam_id].isOpened():
        caps[cam_id] = cv2.VideoCapture(src)
    cap = caps[cam_id]
    while True:
        success, frame = cap.read()
        if not success:
            placeholder = cv2.imencode(".jpg", cv2.UMat(480, 640, cv2.CV_8UC3).get())[1]
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + placeholder.tobytes() + b"\r\n")
            time.sleep(1)
            cap = cv2.VideoCapture(src)
            caps[cam_id] = cap
            continue
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@validate_csrf
def login():
    session.clear()
    error = None
    if request.method == "POST":
        ip       = get_client_ip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # ── Rate Limiting check ──
        if is_rate_limited(ip):
            write_log("LOGIN_RATE_LIMITED", username, ip)
            error = "Too many failed attempts. Please try again later."
            return render_template("login.html", error=error)

        user_record = None
        try:
            conn = get_db_connection()
            cur  = conn.cursor()
            # Fetch hashed password AND role
            cur.execute(
                "SELECT password_hash, role FROM user_credentials WHERE username = %s;",
                (username,)
            )
            user_record = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Database error during login: {e}")
            error = "Database connection issue."

        # ── Password Hash verification (bcrypt via werkzeug) ──
        if user_record and check_password_hash(user_record[0], password):
            session.permanent = True
            session["user"]        = username
            session["role"]        = user_record[1] if user_record[1] else "viewer"
            session["last_active"] = datetime.utcnow().isoformat()
            generate_csrf_token()   # issue fresh CSRF token on login
            write_log("LOGIN_SUCCESS", username, ip)
            return redirect(url_for("dashboard"))
        else:
            record_attempt(ip)      # count failed attempt for rate limiting
            write_log("LOGIN_FAILED", username, ip)
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    user = session.pop("user", "unknown")
    write_log("LOGOUT", user, get_client_ip())
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
@role_required("dashboard")
def dashboard():
    cameras = get_camera_config()
    write_log("VIEW_DASHBOARD", session["user"], get_client_ip())
    return render_template("dashboard.html", cameras=cameras, user=session["user"])


@app.route("/stream/<int:cam_id>")
@login_required
def stream(cam_id):
    # Restrict to valid cam IDs to prevent enumeration abuse
    valid_ids = {cam["id"] for cam in get_camera_config()}
    if cam_id not in valid_ids:
        abort(404)
    response = Response(
        generate_frames(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )
    # Removed wildcard CORS — streams are internal only
    return response


@app.route("/footage")
@login_required
@role_required("footage")
def footage():
    files = sorted(glob.glob(os.path.join(CCTV_FOLDER, "**", "*"), recursive=True))
    media = []
    for f in files:
        if os.path.isfile(f):
            rel   = os.path.relpath(f, CCTV_FOLDER)
            size  = os.path.getsize(f)
            mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
            ext   = os.path.splitext(f)[1].lower()
            media.append({"name": rel, "size": size, "modified": mtime, "ext": ext})
    write_log("VIEW_FOOTAGE", session["user"], get_client_ip())
    return render_template("footage.html", media=media, user=session["user"])


@app.route("/footage/file/<path:filename>")
@login_required
@role_required("footage")
def serve_footage(filename):
    write_log(f"DOWNLOAD_FOOTAGE file={filename}", session["user"], get_client_ip())
    return send_from_directory(CCTV_FOLDER, filename)


@app.route("/logs")
@login_required
@role_required("logs")
def logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            lines = f.readlines()[-200:]
    lines = [l.strip() for l in reversed(lines)]
    write_log("VIEW_LOGS", session["user"], get_client_ip())
    return render_template("logs.html", lines=lines, user=session["user"])


@app.route("/api/cameras")
@login_required
@role_required("cameras")
def api_cameras():
    return jsonify(get_camera_config())


@app.route("/api/logs")
@login_required
@role_required("logs")
def api_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            lines = [l.strip() for l in f.readlines()[-100:]]
    return jsonify({"logs": list(reversed(lines))})


@app.route("/proxy/stream/<int:cam_id>")
@login_required
@role_required("cameras")
def proxy_stream(cam_id):
    ngrok = os.environ.get("NGROK_URL", "").rstrip("/")
    if not ngrok:
        return jsonify({"error": "NGROK_URL not set"}), 500
    url = f"{ngrok}/stream/{cam_id}"
    try:
        r = req.get(
            url,
            headers={"cf-access-skip-interstitial": "true", "User-Agent": "python-requests/2.31.0"},
            stream=True,
            timeout=30
        )
        return Response(
            r.iter_content(chunk_size=1024),
            status=r.status_code,
            content_type=r.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/proxy", defaults={"path": ""})
@app.route("/proxy/<path:path>", methods=["GET", "POST"])
@login_required
def proxy(path):
    ngrok = os.getenv("NGROK_URL", "")
    if not ngrok:
        return jsonify({"error": "NGROK_URL not set"}), 500
    ngrok = ngrok.rstrip("/")
    url = f"{ngrok}/{path}"
    try:
        r = req.request(
            method=request.method,
            url=url,
            headers={**{k: v for k, v in request.headers if k != "Host"}, "ngrok-skip-browser-warning": "true", "cf-access-skip-interstitial": "true", "User-Agent": "python-requests/2.31.0"},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            stream=True,
            timeout=10
        )
        return Response(r.iter_content(chunk_size=1024), status=r.status_code, content_type=r.headers.get("Content-Type"))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/stream-url")
@login_required
def stream_url():
    ngrok = os.environ.get("NGROK_URL", "").rstrip("/")
    return jsonify({"url": f"{ngrok}/stream/0"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
