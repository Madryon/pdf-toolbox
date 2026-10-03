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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise VideoToolError("Audio extraction timed out.")

    if result.returncode != 0 or not os.path.exists(out_path):
        stderr = result.stderr.decode(errors="ignore")[-2000:]
        raise VideoToolError(f"ffmpeg failed to extract audio: {stderr}")

    return out_path
import pdftool

def video_to_images(in_path: str, out_dir: str, fmt: str = "png", quality: int = 85,
                    max_frames: int | None = None, fps: int | None = None, max_dimension: int | None = None) -> list[str]:
    """Extract video frames to images using pdftool.video_to_frames.

    Wraps any OSError from ffmpeg/I/O with a user‑friendly VideoToolError.
    Returns list of image file paths.
    """
    try:
        return pdftool.video_to_frames(
            str(in_path), str(out_dir), fmt=fmt, quality=quality,
            max_frames=max_frames, fps=fps, max_dimension=max_dimension
        )
    except OSError as e:
        raise VideoToolError(f"Failed to process video due to I/O error: {e}")
    except Exception as e:
        # Re‑raise known VideoToolError or wrap unexpected errors
        if isinstance(e, VideoToolError):
            raise
        raise VideoToolError(str(e))
