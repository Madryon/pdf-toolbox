import os
import time
import uuid
from pathlib import Path
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename
import pdftool

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


# ─────────────────────────────────────────────────────────────
# NEW ROUTE: Split PDF
# ─────────────────────────────────────────────────────────────

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
            # Parse page ranges like "1-3,4-7,8-10" or "1,3,5-10"
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

        # If only one file, return it directly; otherwise zip them
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


# ─────────────────────────────────────────────────────────────
# NEW ROUTE: Video to Images / PDF
# ─────────────────────────────────────────────────────────────

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
        target_fps = request.form.get("fps")
        target_fps = float(target_fps) if target_fps else None
        max_frames = request.form.get("max_frames")
        max_frames = int(max_frames) if max_frames else None
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
        target_fps = request.form.get("fps")
        target_fps = float(target_fps) if target_fps else None
        max_frames = request.form.get("max_frames")
        max_frames = int(max_frames) if max_frames else None
        max_dim = int(request.form.get("max_dimension", 0))
        max_dim = max_dim if max_dim > 0 else None
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


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "file too large (max 500MB)"}), 413


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/") or request.path in (
        "/merge", "/compress", "/convert", "/pdf-to-word", "/images-to-pdf",
        "/split", "/video-to-images", "/video-to-pdf"
    ):
        return jsonify({"error": "not found"}), 404
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
