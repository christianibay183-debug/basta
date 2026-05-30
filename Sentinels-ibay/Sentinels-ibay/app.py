from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, send_from_directory
from functools import wraps
from datetime import datetime
import os
import json
import cv2
import glob
import logging
import time
import requests as req

# Security and Database dependencies
from dotenv import load_dotenv
import psycopg2
from werkzeug.security import check_password_hash

load_dotenv()

app = Flask(__name__, template_folder="Frontend/html", static_folder="Frontend", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key-for-local-dev")

CCTV_FOLDER = os.path.join(os.path.dirname(__file__), "cctv_footage")
LOG_FILE    = os.path.join(os.path.dirname(__file__), "logs", "access.log")

os.makedirs(CCTV_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def get_db_connection():
    # Check if a unified database URL string is provided (e.g., Neon or Railway)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)

    # Fallback to individual local parameters if DATABASE_URL isn't set
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

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

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

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# Secured Login Route targeting your user_credentials table
@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr

        user_record = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # Query the user_credentials table setup in pgAdmin / Neon
            cur.execute("SELECT password_hash FROM user_credentials WHERE username = %s;", (username,))
            user_record = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Database error during login: {e}")
            error = "Database connection issue."

        # Verify hash match safely without exposing plain-text credentials
        if user_record and check_password_hash(user_record[0], password):
            session["user"] = username
            write_log("LOGIN_SUCCESS", username, ip)
            return redirect(url_for("dashboard"))
        else:
            write_log("LOGIN_FAILED", username, ip)
            error = "Invalid username or password."

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    user = session.pop("user", "unknown")
    write_log("LOGOUT", user, request.remote_addr)
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    cameras = get_camera_config()
    write_log("VIEW_DASHBOARD", session["user"], request.remote_addr)
    return render_template("dashboard.html", cameras=cameras, user=session["user"])

@app.route("/stream/<int:cam_id>")
def stream(cam_id):
    response = Response(
        generate_frames(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route("/footage")
@login_required
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
    write_log("VIEW_FOOTAGE", session["user"], request.remote_addr)
    return render_template("footage.html", media=media, user=session["user"])

@app.route("/footage/file/<path:filename>")
@login_required
def serve_footage(filename):
    write_log(f"DOWNLOAD_FOOTAGE file={filename}", session["user"], request.remote_addr)
    return send_from_directory(CCTV_FOLDER, filename)

@app.route("/logs")
@login_required
def logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            lines = f.readlines()[-200:]
    lines = [l.strip() for l in reversed(lines)]
    write_log("VIEW_LOGS", session["user"], request.remote_addr)
    return render_template("logs.html", lines=lines, user=session["user"])

@app.route("/api/cameras")
@login_required
def api_cameras():
    return jsonify(get_camera_config())

@app.route("/api/logs")
@login_required
def api_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            lines = [l.strip() for l in f.readlines()[-100:]]
    return jsonify({"logs": list(reversed(lines))})

@app.route("/proxy/stream/<int:cam_id>")
@login_required
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
def stream_url():
    ngrok = os.environ.get("NGROK_URL", "").rstrip("/")
    return jsonify({"url": f"{ngrok}/stream/0"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
