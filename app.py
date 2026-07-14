import os
import time
import uuid
from pathlib import Path
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename
import pdftool
import pdftool_scan as scanner
import pdftool_video as vidtool

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False


def _save_upload(file_storage, job_dir, original_name):
    safe = secure_filename(original_name or "file") or "file"
    fp = job_dir / safe
    file_storage.save(fp)
    return fp


def _cleanup_old(max_age_seconds=3600):
    cutoff = time.time() - max_age_seconds
    for d in (UPLOAD_DIR, OUTPUT_DIR):
        if not d.exists():
            continue
        for child in d.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    for sub in child.rglob("*"):
                        try:
                            sub.unlink()
                        except OSError:
                            pass
                    try:
                        child.rmdir()
                    except OSError:
                        pass
                elif child.is_file() and child.stat().st_mtime < cutoff:
                    child.unlink()
            except OSError:
                pass


@app.route("/")
def index():
    _cleanup_old()
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "version": "2.0"})


@app.route("/merge", methods=["POST"])
def merge_route():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files provided"}), 400
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    inputs = []
    for f in files:
        if not f.filename:
            continue
        fp = _save_upload(f, job_dir, f.filename)
        inputs.append(str(fp))
    if not inputs:
        return jsonify({"error": "no valid files"}), 400
    output_path = OUTPUT_DIR / f"merged_{job_id}.pdf"
    try:
        pdftool.merge_pdfs(inputs, str(output_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return send_file(
        str(output_path),
        as_attachment=True,
        download_name="merged.pdf",
        mimetype="application/pdf",
    )


@app.route("/compress", methods=["POST"])
def compress_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    try:
        quality = max(1, min(100, int(request.form.get("quality", 60))))
        max_dim = int(request.form.get("max_dimension", 1600))
        dpi = int(request.form.get("dpi", 120))
        mode = request.form.get("mode", "auto")
        if mode not in ("auto", "native", "rasterize"):
            mode = "auto"
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    ext = in_path.suffix.lower()
    out_ext = ext if ext in (".pdf",) else ext
    out_name = f"{in_path.stem}_compressed{ext}"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"
    try:
        if ext == ".pdf":
            pdftool.compress_pdf(
                str(in_path), str(out_path),
                quality=quality, max_dimension=max_dim,
                dpi=dpi, mode=mode,
            )
        elif ext in pdftool.IMAGE_EXTENSIONS:
            pdftool.compress_image(
                str(in_path), str(out_path),
                quality=quality, max_dimension=max_dim if max_dim > 0 else None,
            )
        else:
            return jsonify({"error": f"unsupported file type: {ext}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return send_file(str(out_path), as_attachment=True, download_name=out_name)


@app.route("/convert", methods=["POST"])
def convert_route():
    f = request.files.get("file")
    fmt = (request.form.get("format") or "png").lower()
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    try:
        quality = max(1, min(100, int(request.form.get("quality", 85))))
        dpi = max(50, min(600, int(request.form.get("dpi", 150))))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    in_ext = in_path.suffix.lower()
    if in_ext == ".pdf" and fmt in {x.lstrip(".") for x in pdftool.IMAGE_EXTENSIONS}:
        out_dir = OUTPUT_DIR / f"pdf2img_{job_id}"
        try:
            paths = pdftool.pdf_to_images(
                str(in_path), str(out_dir), fmt=fmt, dpi=dpi, quality=quality
            )
            zip_path = OUTPUT_DIR / f"{job_id}_pages.zip"
            pdftool.make_zip(paths, str(zip_path))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return send_file(
            str(zip_path), as_attachment=True,
            download_name=f"{in_path.stem}_pages.zip",
            mimetype="application/zip",
        )
    if fmt not in {x.lstrip(".") for x in pdftool.IMAGE_EXTENSIONS} and fmt != "pdf":
        return jsonify({"error": f"unsupported output format: {fmt}"}), 400
    out_name = f"{in_path.stem}.{fmt}"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"
    try:
        paths = pdftool.convert_file(
            str(in_path), str(out_path), quality=quality, dpi=dpi
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if len(paths) == 1:
        return send_file(paths[0], as_attachment=True, download_name=out_name)
    zip_path = OUTPUT_DIR / f"{job_id}_converted.zip"
    pdftool.make_zip(paths, str(zip_path))
    return send_file(
        str(zip_path), as_attachment=True,
        download_name=f"{in_path.stem}_converted.zip",
        mimetype="application/zip",
    )


@app.route("/pdf-to-word", methods=["POST"])
def pdf_to_word_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = f"{in_path.stem}.docx"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"
    try:
        pdftool.pdf_to_word(str(in_path), str(out_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=out_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.route("/images-to-pdf", methods=["POST"])
def images_to_pdf_route():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files provided"}), 400
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    inputs = []
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in pdftool.IMAGE_EXTENSIONS:
            continue
        fp = _save_upload(f, job_dir, f.filename)
        inputs.append(str(fp))
    if not inputs:
        return jsonify({"error": "no valid image files"}), 400
    out_path = OUTPUT_DIR / f"{job_id}_images.pdf"
    try:
        pdftool.images_to_pdf(inputs, str(out_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return send_file(
        str(out_path), as_attachment=True,
        download_name="images.pdf", mimetype="application/pdf",
    )


# NEW: Split PDF route
@app.route("/split", methods=["POST"])
def split_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400

    split_type = request.form.get("split_type", "pages")

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_dir = OUTPUT_DIR / f"split_{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        if split_type == "pages":
            ranges_str = request.form.get("ranges", "")
            if not ranges_str:
                return jsonify({"error": "no page ranges provided"}), 400

            ranges = []
            for part in ranges_str.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    start = int(a.strip())
                    end = int(b.strip()) if b.strip() else None
                    ranges.append((start, end))
                else:
                    p = int(part.strip())
                    ranges.append((p, p))

            paths = pdftool.split_pdf_by_pages(str(in_path), str(out_dir), ranges)

        elif split_type == "chunks":
            try:
                pages_per_chunk = int(request.form.get("pages_per_chunk", 1))
                if pages_per_chunk < 1:
                    pages_per_chunk = 1
            except (TypeError, ValueError):
                return jsonify({"error": "invalid pages per chunk"}), 400

            paths = pdftool.split_pdf_by_chunks(str(in_path), str(out_dir), pages_per_chunk)

        else:
            return jsonify({"error": "invalid split type"}), 400

        if not paths:
            return jsonify({"error": "no output files generated"}), 400

        if len(paths) == 1:
            return send_file(
                paths[0], as_attachment=True,
                download_name=Path(paths[0]).name,
                mimetype="application/pdf",
            )

        zip_path = OUTPUT_DIR / f"{job_id}_split.zip"
        pdftool.make_zip(paths, str(zip_path))
        return send_file(
            str(zip_path), as_attachment=True,
            download_name=f"{in_path.stem}_split.zip",
            mimetype="application/zip",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to Images route
@app.route("/video-to-images", methods=["POST"])
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
        paths = pdftool.video_to_frames(
            str(in_path), str(out_dir),
            fmt=fmt, quality=quality,
            max_frames=max_frames, fps=target_fps
        )

        if not paths:
            return jsonify({"error": "no frames could be extracted"}), 400

        zip_path = OUTPUT_DIR / f"{job_id}_frames.zip"
        pdftool.make_zip(paths, str(zip_path))
        return send_file(
            str(zip_path), as_attachment=True,
            download_name=f"{in_path.stem}_frames.zip",
            mimetype="application/zip",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to PDF route
@app.route("/video-to-pdf", methods=["POST"])
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
        return send_file(
            str(out_path), as_attachment=True,
            download_name=out_name,
            mimetype="application/pdf",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to MP3 (extract audio from an uploaded video file via ffmpeg)
@app.route("/video-to-mp3", methods=["POST"])
def video_to_mp3_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    bitrate = request.form.get("bitrate", "192k")

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

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name, mimetype="audio/mpeg",
    )


# NEW: Video Downloader (download from a URL via yt-dlp; 1000s of sites)




@app.route("/watermark-text", methods=["POST"])
def watermark_text_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400

    try:
        text = request.form.get("text", "CONFIDENTIAL").strip() or "CONFIDENTIAL"
        font_size = max(10, min(200, int(request.form.get("font_size", 60))))
        opacity = max(0.05, min(1.0, float(request.form.get("opacity", 0.3))))
        angle = int(request.form.get("angle", 45))
        spacing = max(50, int(request.form.get("spacing", 200)))
        # Parse color
        color_str = request.form.get("color", "128,128,128")
        color = tuple(int(x.strip()) for x in color_str.split(",") if x.strip().isdigit())[:3]
        if len(color) != 3:
            color = (128, 128, 128)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = f"{in_path.stem}_watermarked.pdf"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        pdftool.add_text_watermark(
            str(in_path), str(out_path),
            text=text, font_size=font_size,
            opacity=opacity, color=color,
            angle=angle, spacing=spacing
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Watermark PDF - Image
@app.route("/watermark-image", methods=["POST"])
def watermark_image_route():
    f = request.files.get("file")
    img = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "no PDF file provided"}), 400
    if not img or not img.filename:
        return jsonify({"error": "no watermark image provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400

    try:
        opacity = max(0.05, min(1.0, float(request.form.get("opacity", 0.3))))
        position = request.form.get("position", "center")
        if position not in ("center", "top-left", "top-right", "bottom-left", "bottom-right"):
            position = "center"
        scale = max(0.05, min(1.0, float(request.form.get("scale", 0.3))))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    img_path = _save_upload(img, job_dir, img.filename)
    out_name = f"{in_path.stem}_watermarked.pdf"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        pdftool.add_image_watermark(
            str(in_path), str(out_path), str(img_path),
            opacity=opacity, position=position, scale=scale
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Lock/Encrypt PDF
@app.route("/lock", methods=["POST"])
def lock_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400

    user_password = request.form.get("user_password", "")
    owner_password = request.form.get("owner_password", "")

    if not user_password and not owner_password:
        return jsonify({"error": "please provide at least one password"}), 400

    try:
        allow_printing = request.form.get("allow_printing", "true").lower() == "true"
        allow_copying = request.form.get("allow_copying", "true").lower() == "true"
        allow_modifying = request.form.get("allow_modifying", "false").lower() == "true"
        allow_annotating = request.form.get("allow_annotating", "false").lower() == "true"
        allow_form_filling = request.form.get("allow_form_filling", "false").lower() == "true"
    except Exception:
        allow_printing = True
        allow_copying = True
        allow_modifying = False
        allow_annotating = False
        allow_form_filling = False

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = f"{in_path.stem}_locked.pdf"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        pdftool.lock_pdf(
            str(in_path), str(out_path),
            user_password=user_password,
            owner_password=owner_password,
            allow_printing=allow_printing,
            allow_copying=allow_copying,
            allow_modifying=allow_modifying,
            allow_annotating=allow_annotating,
            allow_form_filling=allow_form_filling
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Unlock/Decrypt PDF
@app.route("/unlock", methods=["POST"])
def unlock_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if Path(f.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "please upload a PDF file"}), 400

    password = request.form.get("password", "")

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_name = f"{in_path.stem}_unlocked.pdf"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"

    try:
        pdftool.unlock_pdf(str(in_path), str(out_path), password=password)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# ─────────────────────────────────────────────────────────────
# DOC SCANNER routes
# ─────────────────────────────────────────────────────────────

@app.route("/scan/health")
def scan_health():
    return jsonify({
        "ok": True,
        "ocr_available": scanner.ocr_available(),
    })


@app.route("/scan/process", methods=["POST"])
def scan_process_route():
    """
    Apply scan pipeline (perspective, filter, brightness/contrast/sharpness,
    rotate, crop) to one uploaded image, return the processed image as JPEG.
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file provided"}), 400

    # Parse scan settings
    def _f(name, default):
        v = request.form.get(name)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    filter_name = (request.form.get("filter") or "magic_color").lower()
    if filter_name not in ("original", "bw", "grayscale", "magic_color", "enhanced", "sharpen"):
        filter_name = "magic_color"

    perspective = str(request.form.get("perspective", "")).lower() in ("1", "true", "yes", "on")
    rotate = _f("rotate", 0)
    brightness = _f("brightness", 1.0)
    contrast = _f("contrast", 1.0)
    sharpness = _f("sharpness", 1.0)

    crop = None
    if request.form.get("crop_x") not in (None, ""):
        try:
            crop = {
                "x": float(request.form.get("crop_x", 0)),
                "y": float(request.form.get("crop_y", 0)),
                "w": float(request.form.get("crop_w", 0)),
                "h": float(request.form.get("crop_h", 0)),
            }
        except (TypeError, ValueError):
            crop = None

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    in_path = _save_upload(f, job_dir, f.filename)
    out_path = OUTPUT_DIR / f"{job_id}_scan.jpg"

    try:
        scanner.process_scan(
            str(in_path), str(out_path),
            perspective=perspective,
            filter_name=filter_name,
            brightness=brightness,
            contrast=contrast,
            sharpness=sharpness,
            rotate=rotate,
            crop=crop,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=False,
        download_name=f"{job_id}_scan.jpg",
        mimetype="image/jpeg",
    )


@app.route("/scan/build", methods=["POST"])
def scan_build_route():
    """
    Build the final DOCX from one or more processed scan images.
    Each uploaded image is one page.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no scan pages provided"}), 400

    use_ocr = str(request.form.get("ocr", "true")).lower() in ("1", "true", "yes", "on")
    ocr_lang = (request.form.get("ocr_lang") or "eng").strip() or "eng"
    out_format = (request.form.get("format") or "docx").lower()
    if out_format not in ("docx", "pdf"):
        out_format = "docx"

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / f"scan_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    page_paths = []
    for idx, f in enumerate(files, start=1):
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
            continue
        safe_name = f"page_{idx:03d}{ext or '.jpg'}"
        out_fp = job_dir / safe_name
        f.save(out_fp)
        page_paths.append(str(out_fp))

    if not page_paths:
        return jsonify({"error": "no valid image pages provided"}), 400

    if out_format == "pdf":
        out_name = f"scan_{job_id}.pdf"
        out_path = OUTPUT_DIR / out_name
        try:
            scanner.images_to_pdf_simple(page_paths, str(out_path))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return send_file(
            str(out_path), as_attachment=True,
            download_name=out_name,
            mimetype="application/pdf",
        )

    # docx
    out_name = f"scan_{job_id}.docx"
    out_path = OUTPUT_DIR / out_name
    try:
        scanner.images_to_docx(
            page_paths, str(out_path),
            ocr_lang=ocr_lang, use_ocr=use_ocr
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ─────────────────────────────────────────────────────────────
# QR CODE GENERATOR
# ─────────────────────────────────────────────────────────────

@app.route("/qr-generate", methods=["POST"])
def qr_generate_route():
    """
    Generate a QR code PNG from any text/URL -- works for a plain
    website URL, a Google Drive share link, a link to a hosted PDF,
    or any other text.
    """
    data = (request.form.get("data") or "").strip()
    if not data:
        return jsonify({"error": "no text or URL provided"}), 400

    try:
        box_size = max(1, min(50, int(request.form.get("box_size", 10))))
        border = max(1, min(20, int(request.form.get("border", 4))))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric option"}), 400

    fill_color = (request.form.get("fill_color") or "black").strip() or "black"
    back_color = (request.form.get("back_color") or "white").strip() or "white"
    error_correction = (request.form.get("error_correction") or "M").strip().upper()
    if error_correction not in ("L", "M", "Q", "H"):
        error_correction = "M"

    job_id = uuid.uuid4().hex
    logo_path = None
    job_dir = None

    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        ext = Path(logo_file.filename).suffix.lower()
        if ext not in pdftool.IMAGE_EXTENSIONS:
            return jsonify({"error": f"unsupported logo image type: {ext}"}), 400
        job_dir = UPLOAD_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        logo_path = _save_upload(logo_file, job_dir, logo_file.filename)
        # logo forces high error correction so the code stays scannable
        error_correction = "H"

    out_path = OUTPUT_DIR / f"{job_id}_qr.png"

    try:
        pdftool.generate_qr_code(
            data, str(out_path),
            box_size=box_size, border=border,
            fill_color=fill_color, back_color=back_color,
            error_correction=error_correction,
            logo_path=str(logo_path) if logo_path else None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        str(out_path), as_attachment=True,
        download_name="qrcode.png",
        mimetype="image/png",
    )


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "file too large (max 500MB)"}), 413


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/") or request.path in (
        "/merge", "/compress", "/convert", "/pdf-to-word", "/images-to-pdf",
        "/split", "/video-to-images", "/video-to-pdf", "/watermark-text", "/watermark-image", "/lock", "/unlock",
        "/video-to-mp3", "/download", "/qr-generate",
        "/scan/process", "/scan/build", "/scan/health"
    ):
        return jsonify({"error": "not found"}), 404
    return jsonify({"error": "not found"}), 404


# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 5000))
#     app.run(host="0.0.0.0", port=port, debug=False)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
