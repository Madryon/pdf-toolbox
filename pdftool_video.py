"""
pdftool_video.py — video/audio helpers used by app.py

Provides:
  - VideoToolError
  - extract_audio(in_path, out_path, bitrate="192k")
  - download_video(url, job_dir, fmt="mp4", quality="best")
"""

import os
import shutil
import subprocess
from pathlib import Path

import yt_dlp


class VideoToolError(Exception):
    """Raised for expected/user-facing video/audio processing failures."""
    pass


def _ffmpeg_bin():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoToolError(
            "ffmpeg is not installed on the server. "
            "Make sure ffmpeg is available in the deploy environment (e.g. nixpacks.toml)."
        )
    return ffmpeg


def extract_audio(in_path: str, out_path: str, bitrate: str = "192k") -> str:
    """
    Extract audio from a video file into an mp3 using ffmpeg.
    """
    in_path = str(in_path)
    out_path = str(out_path)

    if not os.path.exists(in_path):
        raise VideoToolError("Input video file not found.")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _ffmpeg_bin()

    cmd = [
        ffmpeg,
        "-y",                # overwrite output
        "-i", in_path,
        "-vn",               # no video
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        out_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise VideoToolError("Audio extraction timed out.")

    if result.returncode != 0 or not os.path.exists(out_path):
        stderr = result.stderr.decode(errors="ignore")[-2000:]
        raise VideoToolError(f"ffmpeg failed to extract audio: {stderr}")

    return out_path
