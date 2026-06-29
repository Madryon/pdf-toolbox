

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp


class VideoToolError(Exception):
    """Raised for expected, user-facing failures (bad url, no ffmpeg, etc.)."""
    pass


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


# ─────────────────────────────────────────────────────────────
# Video file -> MP3 (uploaded file, local ffmpeg transcode)
# ─────────────────────────────────────────────────────────────

def extract_audio(input_path, output_path, bitrate="192k"):
    """
    Extract the audio track from a video file and transcode it to MP3
    at the given bitrate, using ffmpeg.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise VideoToolError(
            "ffmpeg isn't installed on this server, so audio extraction "
            "isn't available right now."
        )
    if not re.fullmatch(r"\d{2,4}k", str(bitrate)):
        bitrate = "192k"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin, "-y", "-i", str(input_path),
        "-vn",                     # drop video stream
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        "-ar", "44100",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
        raise VideoToolError(
            "Couldn't extract audio from that file — it may not contain "
            "a valid audio track, or the format isn't supported."
        )
    return output_path


# ─────────────────────────────────────────────────────────────
# URL video/audio downloader (yt-dlp)
# ─────────────────────────────────────────────────────────────

# YouTube aggressively blocks/rate-limits server-side (datacenter IP)
# extraction, so attempts from a host like Render fail unpredictably
# and just waste the request — refuse up front with a clear message
# instead of letting yt-dlp time out or get a confusing error.
_BLOCKED_HOST_PATTERNS = (
    r"(?:^|\.)youtube\.com$",
    r"(?:^|\.)youtube-nocookie\.com$",
    r"(?:^|\.)youtu\.be$",
)


def _is_blocked_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(re.search(p, host) for p in _BLOCKED_HOST_PATTERNS)


def _friendly_download_error(msg):
    low = msg.lower()
    if "unsupported url" in low or "no extractor" in low:
        return "That link doesn't look like it's from a supported site."
    if "private" in low:
        return "This content is private and can't be downloaded."
    if "sign in" in low or "login required" in low or "age" in low:
        return "This content requires login or age verification, so it can't be downloaded here."
    if "403" in low or "forbidden" in low:
        return "The source site blocked this download. Try a different link or site."
    if "404" in low or "unable to download webpage" in low:
        return "Couldn't find that content — double check the link."
    if "max_filesize" in low or "exceeds" in low:
        return "That file is too large to download here (500MB limit)."
    return "Couldn't download that link. Double-check the URL, or try a different supported site."


def download_video(url, output_dir, fmt="mp4", quality="best"):
    """
    Download a video (or just its audio) from a URL using yt-dlp.

    Args:
        url: source page/video URL
        output_dir: directory to download into
        fmt: "mp4" or "mp3"
        quality: "best" | "720" | "480" | "360" | "worst" (mp4 only)
    Returns:
        path to the downloaded (and, for mp3, transcoded) file
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        raise VideoToolError("Please provide a valid http(s) URL.")

    if _is_blocked_url(url):
        raise VideoToolError(
            "YouTube and YouTube Shorts links aren't supported — Google "
            "blocks server-side downloads from hosts like this one. Try "
            "Instagram, TikTok, Reddit, Twitter/X, Facebook, or another "
            "supported site instead."
        )

    has_ffmpeg = ffmpeg_available()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(output_dir / "%(id)s.%(ext)s")

    postprocessors = []
    if fmt == "mp3":
        if has_ffmpeg:
            format_selector = "bestaudio/best"
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            # No ffmpeg available -> can't transcode. Grab a ready-made
            # audio-only stream as-is instead of failing outright.
            format_selector = "bestaudio[ext=m4a]/bestaudio"
    else:
        height_map = {"720": 720, "480": 480, "360": 360}
        if has_ffmpeg:
            if quality in height_map:
                h = height_map[quality]
                format_selector = (
                    f"best[height<={h}][ext=mp4]/best[height<={h}]/"
                    f"bestvideo[height<={h}]+bestaudio/best"
                )
            elif quality == "worst":
                format_selector = "worst[ext=mp4]/worstvideo+worstaudio/worst"
            else:
                format_selector = "best[ext=mp4]/bestvideo+bestaudio/best"
        else:
            # No ffmpeg -> can't mux separate video+audio streams, so
            # restrict to formats that are already a single playable file.
            format_selector = "best[ext=mp4]/best"

    ydl_opts = {
        "format": format_selector,
        "outtmpl": out_template,
        "postprocessors": postprocessors,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "nocheckcertificate": True,
        "socket_timeout": 30,
        "retries": 3,
        "max_filesize": 500 * 1024 * 1024,  # 500MB safety cap
    }
    if fmt != "mp3" and has_ffmpeg:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise VideoToolError("Couldn't read that link.")
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise VideoToolError("No downloadable media found at that link.")
                info = entries[0]
            final_path = ydl.prepare_filename(info)
            # A postprocessor (mp3/mp4 conversion) may have changed the
            # file extension — find the actual resulting file on disk.
            stem = Path(final_path).stem
            candidates = [p for p in output_dir.glob(stem + ".*") if p.is_file()]
            if candidates:
                final_path = str(max(candidates, key=lambda p: p.stat().st_mtime))
    except VideoToolError:
        raise
    except yt_dlp.utils.DownloadError as e:
        raise VideoToolError(_friendly_download_error(str(e)))
    except Exception as e:
        raise VideoToolError(_friendly_download_error(str(e)))

    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        raise VideoToolError("The download finished but produced no usable file.")
    return final_path
