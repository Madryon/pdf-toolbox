import os
import time
import uuid
from pathlib import Path
from flask import Flask, request, send_file, render_template, jsonify, abort
from werkzeug.utils import secure_filename
import pdftool

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
DOWNLOAD_DIR = BASE_DIR / "downloads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False

RESULT_TTL_SECONDS = 24 * 60 * 60
UPLOAD_TTL_SECONDS = 60 * 60


def _save_upload(file_storage, job_dir, original_name):
    safe = secure_filename(original_name or "file") or "file"
    fp = job_dir / safe
    file_storage.save(fp)
    return fp


def _register_result(src_path, display_name):
    result_id = uuid.uuid4().hex
    safe_name = secure_filename(display_name) or "file"
    final_path = DOWNLOAD_DIR / f"{result_id}_{safe_name}"
    if src_path != str(final_path):
        import shutil
        shutil.copy2(src_path, final_path)
    size = final_path.stat().st_size
    return {
        "id": result_id,
        "filename": safe_name,
        "size": size,
        "created": int(time.time()),
    }


def _cleanup_old():
    now = time.time()
    for d, ttl in ((UPLOAD_DIR, UPLOAD_TTL_SECONDS), (OUTPUT_DIR, UPLOAD_TTL_SECONDS), (DOWNLOAD_DIR, RESULT_TTL_SECONDS)):
        if not d.exists():
            continue
        cutoff = now - ttl
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


def _delete_result(result_id):
    for fp in DOWNLOAD_DIR.glob(f"{result_id}_*"):
        try:
            fp.unlink()
            return True
        except OSError:
            return False
    return False


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
    out_path = OUTPUT_DIR / f"merged_{job_id}.pdf"
    try:
        pdftool.merge_pdfs(inputs, str(out_path))
        result = _register_result(str(out_path), "merged.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


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
        result = _register_result(str(out_path), out_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


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
    image_exts = {x.lstrip(".") for x in pdftool.IMAGE_EXTENSIONS}
    docx_exts = {x.lstrip(".") for x in pdftool.DOCX_EXTENSIONS}
    xlsx_exts = {x.lstrip(".") for x in pdftool.XLSX_EXTENSIONS}
    if in_ext == ".pdf" and fmt in image_exts:
        out_dir = OUTPUT_DIR / f"pdf2img_{job_id}"
        try:
            paths = pdftool.pdf_to_images(
                str(in_path), str(out_dir), fmt=fmt, dpi=dpi, quality=quality
            )
            zip_name = f"{in_path.stem}_pages.zip"
            zip_path = OUTPUT_DIR / zip_name
            pdftool.make_zip(paths, str(zip_path))
            result = _register_result(str(zip_path), zip_name)
            result["pages"] = len(paths)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"result": result})
    allowed_formats = image_exts | docx_exts | xlsx_exts | {"pdf"}
    if fmt not in allowed_formats:
        return jsonify({"error": f"unsupported output format: {fmt}"}), 400
    out_name = f"{in_path.stem}.{fmt}"
    out_path = OUTPUT_DIR / f"{job_id}_{out_name}"
    try:
        paths = pdftool.convert_file(
            str(in_path), str(out_path), quality=quality, dpi=dpi
        )
        if len(paths) == 1:
            result = _register_result(paths[0], out_name)
        else:
            zip_name = f"{in_path.stem}_converted.zip"
            zip_path = OUTPUT_DIR / zip_name
            pdftool.make_zip(paths, str(zip_path))
            result = _register_result(str(zip_path), zip_name)
            result["pages"] = len(paths)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


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
        result = _register_result(str(out_path), "images.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


@app.route("/download/<result_id>")
def download_result(result_id):
    matches = list(DOWNLOAD_DIR.glob(f"{result_id}_*"))
    if not matches:
        abort(404)
    fp = matches[0]
    download_name = fp.name.split("_", 1)[1] if "_" in fp.name else fp.name
    return send_file(
        str(fp),
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/delete/<result_id>", methods=["POST"])
def delete_result(result_id):
    ok = _delete_result(result_id)
    return jsonify({"ok": ok})


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "file too large (max 500MB)"}), 413


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
