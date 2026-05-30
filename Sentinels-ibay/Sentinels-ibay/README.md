# 📷 Sentinels Surveillance System

A web-based CCTV monitoring dashboard built with Python (Flask) and OpenCV.  
Features live camera feeds, footage archive, access logs, and secure login.

---

## 🗂 Project Structure

```
cctv-system/
├── app.py               # Main Flask application
├── cameras.json         # Camera configuration
├── requirements.txt     # Python dependencies
├── Procfile             # For Railway / Heroku
├── railway.toml         # Railway deployment config
├── .env.example         # Environment variable template
├── .gitignore
├── cctv_footage/        # 📁 Place your CCTV recordings here
├── logs/                # Auto-generated access logs
└── templates/
    ├── base.html        # Shared layout
    ├── login.html       # Login page
    ├── dashboard.html   # Live feed dashboard
    ├── footage.html     # Footage archive
    └── logs.html        # System logs viewer
```

---

## ⚙️ Setup (Local)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and set a strong SECRET_KEY
```

### 3. Add your cameras
Edit `cameras.json`:
```json
[
  { "id": 0, "name": "Front Door", "source": 0, "location": "Entrance" },
  { "id": 1, "name": "Back Yard", "source": "rtsp://user:pass@192.168.1.x:554/stream1", "location": "Rear" }
]
```
- `source: 0` = first USB/local webcam  
- `source: "rtsp://..."` = IP camera RTSP stream  
- `source: "http://..."` = HTTP MJPEG stream  

### 4. Run
```bash
python app.py
```
Open `http://localhost:5000` → Login: `admin` / `admin123`

---

## 🎞 CCTV Footage Folder

Drop any video or image files into `cctv_footage/` and they will appear in the **Footage Archive** page for download.

Supported: `.mp4`, `.avi`, `.mov`, `.mkv`, `.ts`, `.jpg`, `.jpeg`, `.png`

---

## 🚀 Deploy to Railway

### Requirements
- A [Railway](https://railway.app) account (free tier works)
- Your code pushed to GitHub

### Steps

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial CCTV system"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

2. **Create Railway project**
   - Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
   - Select your repository

3. **Set environment variables in Railway**
   - Go to your service → Variables tab
   - Add: `SECRET_KEY` = (a long random string)
   - Railway sets `PORT` automatically

4. **Domain**
   - Railway → Settings → Networking → Generate Domain  
   - This gives you a public URL like `https://your-app.up.railway.app`

> ⚠️ **Note on live camera streams:** Railway's servers cannot connect to cameras on your local network. For live CCTV streams on Railway, your cameras must be:
> - Accessible via a public RTSP/HTTP URL, OR
> - Exposed via a VPN or port forwarding from your router

---

## 🔒 Making It Publicly Searchable (SEO / Public Access)

For the site to be searchable/public, you need:

| What | Why |
|------|-----|
| **Custom domain** | Looks professional; required for Google indexing (e.g. `mycctv.com`) |
| **HTTPS** | Railway provides this automatically |
| **robots.txt** | Controls which pages search engines index |
| **Public login bypass** (optional) | If you want a public status page without login |
| **sitemap.xml** (optional) | Helps Google discover pages |

Add `robots.txt` to your static folder or as a route:
```python
@app.route("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /dashboard\nDisallow: /footage\nDisallow: /logs\n", 200, {"Content-Type": "text/plain"}
```

> 🔐 Recommended: Keep `/dashboard`, `/footage`, `/logs` behind login. Only expose a public landing/status page if needed.

---

## 🔑 Login Credentials

Default: **admin** / **admin123**

To change, edit `CREDENTIALS` in `app.py`:
```python
CREDENTIALS = {"admin": "your_new_password"}
```
Or use environment variables for production security.

---

## 🛠 Tech Stack

- **Backend:** Python 3.11+, Flask 3.0
- **Streaming:** OpenCV (cv2) MJPEG over HTTP
- **Frontend:** HTML5, CSS3, vanilla JS (no heavy frameworks)
- **Deployment:** Railway + GitHub CI
- **Process Manager:** Gunicorn
