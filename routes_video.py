import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, g, send_file
from utils import UPLOAD_DIR, OUTPUT_DIR, _save_upload
import pdftool
import pdftool_video as vidtool
from extensions import limiter

video_bp = Blueprint("video", __name__)


@video_bp.route("/video-to-images", methods=["POST"])
@limiter.limit("5 per minute")
def video_to_images_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in pdftool.VIDEO_EXTENSIONS:
        return jsonify({"error": f"unsupported video format: {ext}"}), 400

    try:
        fmt = (request.form.get("format") or "png").lower()
        if fmt not in ("png", "jpg", "jpeg", "webp"):
            fmt = "png"
        quality = max(1, min(100, int(request.form.get("quality", 85))))
        target_fps_raw = request.form.get("fps", "").strip()
        target_fps = float(target_fps_raw) if target_fps_raw and target_fps_raw != "auto" else None
        max_frames_raw = request.form.get("max_frames", "").strip()
        max_frames = int(max_frames_raw) if max_frames_raw else None
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_dir = OUTPUT_DIR / f"video_frames_{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = vidtool.video_to_images(
            str(in_path), str(out_dir),
            fmt=fmt, quality=quality,
            max_frames=max_frames, fps=target_fps
        )

        if not paths:
            return jsonify({"error": "no frames could be extracted"}), 400

        zip_path = OUTPUT_DIR / f"{job_id}_frames.zip"
        pdftool.make_zip(paths, str(zip_path))
        g.tool_name = "video-to-images"
        g.output_name = f"{in_path.stem}_frames.zip"
        g.output_path = str(zip_path)
        return send_file(
            str(zip_path), as_attachment=True,
            download_name=f"{in_path.stem}_frames.zip",
            mimetype="application/zip",
        )
    except vidtool.VideoToolError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to PDF route
@video_bp.route("/video-to-pdf", methods=["POST"])
@limiter.limit("5 per minute")
def video_to_pdf_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in pdftool.VIDEO_EXTENSIONS:
        return jsonify({"error": f"unsupported video format: {ext}"}), 400

    try:
        quality = max(1, min(100, int(request.form.get("quality", 75))))
        target_fps_raw = request.form.get("fps", "").strip()
        target_fps = float(target_fps_raw) if target_fps_raw and target_fps_raw != "auto" else None
        max_frames_raw = request.form.get("max_frames", "").strip()
        max_frames = int(max_frames_raw) if max_frames_raw else None
        max_dim_raw = request.form.get("max_dimension", "").strip()
        max_dim = int(max_dim_raw) if max_dim_raw else None
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = f"{in_path.stem}_video.pdf"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        pdftool.video_to_pdf(
            str(in_path), str(out_path),
            quality=quality, max_frames=max_frames,
            fps=target_fps, max_dimension=max_dim
        )
        g.tool_name = "video-to-pdf"
        g.output_name = out_name
        g.output_path = str(out_path)
        return send_file(
            str(out_path), as_attachment=True,
            download_name=out_name,
            mimetype="application/pdf",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to MP3 (extract audio from an uploaded video file via ffmpeg)
@video_bp.route("/video-to-mp3", methods=["POST"])
@limiter.limit("5 per minute")
def video_to_mp3_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in pdftool.VIDEO_EXTENSIONS:
        return jsonify({"error": f"unsupported video format: {ext}"}), 400
    bitrate = request.form.get("bitrate", "192k")
    if bitrate not in ("64k", "128k", "192k", "256k", "320k"):
        bitrate = "192k"

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = Path(secure_filename(f.filename)).stem + ".mp3"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        vidtool.extract_audio(str(in_path), str(out_path), bitrate=bitrate)
    except vidtool.VideoToolError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    g.tool_name = "video-to-mp3"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name, mimetype="audio/mpeg",
    )




