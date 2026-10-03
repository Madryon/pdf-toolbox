import uuid
from pathlib import Path
from flask import Blueprint, request, jsonify, g, send_file
from utils import UPLOAD_DIR, OUTPUT_DIR, _save_upload
import pdftool
from extensions import limiter

image_bp = Blueprint("image", __name__)


@image_bp.route("/images-to-pdf", methods=["POST"])
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
    g.tool_name = "images-to-pdf"
    g.output_name = "images.pdf"
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name="images.pdf", mimetype="application/pdf",
    )


# NEW: Split PDF route

@image_bp.route("/watermark-text", methods=["POST"])
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

    g.tool_name = "watermark-text"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Watermark PDF - Image
@image_bp.route("/watermark-image", methods=["POST"])
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

    g.tool_name = "watermark-image"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Lock/Encrypt PDF


@image_bp.route("/qr-generate", methods=["POST"])
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

    g.tool_name = "qr-generate"
    g.output_name = "qrcode.png"
    g.output_path = str(out_path)
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
