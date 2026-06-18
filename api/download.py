import json
import subprocess
import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Format map: our format key → yt-dlp format selector
FORMAT_SELECTORS = {
    "video_hd":  "best[ext=mp4]/best",
    "video_sd":  "best[height<=480][ext=mp4]/best[height<=480]",
    "mp3":       "bestaudio/best",
    "image_jpg": "best",
    "image_png": "best",
}

QUALITY_SELECTORS = {
    # Video HD qualities
    "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
    "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
    # Video SD qualities
    "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]",
    "360p":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]",
    # Audio
    "320kbps": "bestaudio[abr>=256]/bestaudio/best",
    "128kbps": "bestaudio[abr<=160]/bestaudio/best",
}

EXT_MAP = {
    "video_hd": "mp4",
    "video_sd": "mp4",
    "mp3": "mp3",
    "image_jpg": "jpg",
    "image_png": "png",
}


def get_direct_url(url, fmt, quality=None):
    """Get direct download URL using yt-dlp -g flag"""

    # Select format string
    if quality and quality in QUALITY_SELECTORS:
        fmt_str = QUALITY_SELECTORS[quality]
    else:
        fmt_str = FORMAT_SELECTORS.get(fmt, "best")

    # Base command
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "-f", fmt_str,
        "-g",   # Print URL only
        url
    ]

    # For MP3, we need audio URL
    if fmt == "mp3":
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "-f", fmt_str,
            "-g",
            url
        ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        raise Exception(result.stderr.strip() or "Could not get download URL")

    # yt-dlp -g may return multiple URLs (video + audio for merged formats)
    urls = [u.strip() for u in result.stdout.strip().split("\n") if u.strip()]

    if not urls:
        raise Exception("No download URL found")

    # Return first URL (video) — for merged we return the video stream URL
    # The browser can't merge streams, so we return the best single-file URL
    return urls[0]


def get_info_for_filename(url):
    """Get title for filename"""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            title = data.get("title", "download")
            # Sanitize filename
            safe = "".join(c for c in title if c.isalnum() or c in " -_")[:50].strip()
            return safe or "download"
        except Exception:
            pass
    return "download"


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        url = params.get("url", [None])[0]
        fmt = params.get("format", ["video_hd"])[0]
        quality = params.get("quality", [None])[0]

        if not url:
            self.respond(400, {"error": "Missing url parameter"})
            return

        if fmt not in FORMAT_SELECTORS:
            self.respond(400, {"error": f"Invalid format: {fmt}"})
            return

        try:
            direct_url = get_direct_url(url, fmt, quality)
            filename_base = get_info_for_filename(url)
            ext = EXT_MAP.get(fmt, "mp4")
            filename = f"{filename_base}.{ext}"

            self.respond(200, {
                "url": direct_url,
                "filename": filename,
                "format": fmt,
                "quality": quality or "best"
            })

        except subprocess.TimeoutExpired:
            self.respond(408, {"error": "Timeout — media processing took too long"})
        except Exception as e:
            self.respond(500, {"error": str(e)})

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
