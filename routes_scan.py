import uuid
from pathlib import Path
from flask import Blueprint, request, jsonify, g, send_file
from utils import UPLOAD_DIR, OUTPUT_DIR, _save_upload
import pdftool_scan as scanner
from extensions import limiter

scan_bp = Blueprint("scan", __name__)


@scan_bp.route("/scan/health")
def scan_health():
    return jsonify({
        "ok": True,
        "ocr_available": scanner.ocr_available(),
    })


@scan_bp.route("/scan/process", methods=["POST"])
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

    g.tool_name = "scan/process"
    g.output_name = f"{job_id}_scan.jpg"
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=False,
        download_name=f"{job_id}_scan.jpg",
        mimetype="image/jpeg",
    )


@scan_bp.route("/scan/build", methods=["POST"])
@limiter.limit("5 per minute")
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
        g.tool_name = "scan/build"
        g.output_name = out_name
        g.output_path = str(out_path)
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

    g.tool_name = "scan/build"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ─────────────────────────────────────────────────────────────
# QR CODE GENERATOR
# ─────────────────────────────────────────────────────────────

