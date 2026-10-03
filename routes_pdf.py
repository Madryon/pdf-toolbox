import uuid
from flask import Blueprint, request, jsonify, g, send_file
from utils import UPLOAD_DIR, OUTPUT_DIR, _save_upload
import pdftool

pdf_bp = Blueprint("pdf", __name__)


@pdf_bp.route("/merge", methods=["POST"])
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
    g.tool_name = "merge"
    g.output_name = "merged.pdf"
    g.output_path = str(output_path)
    return send_file(
        str(output_path),
        as_attachment=True,
        download_name="merged.pdf",
        mimetype="application/pdf",
    )


@pdf_bp.route("/compress", methods=["POST"])
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
    g.tool_name = "compress"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(str(out_path), as_attachment=True, download_name=out_name)


@pdf_bp.route("/convert", methods=["POST"])
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
        g.tool_name = "convert"
        g.output_name = f"{in_path.stem}_pages.zip"
        g.output_path = str(zip_path)
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
        safe_path = Path(paths[0]).resolve()
        if OUTPUT_DIR.resolve() not in safe_path.parents:
            return jsonify({"error": "invalid output path"}), 400
        g.tool_name = "convert"
        g.output_name = out_name
        g.output_path = str(safe_path)
        return send_file(str(safe_path), as_attachment=True, download_name=out_name)
    zip_path = OUTPUT_DIR / f"{job_id}_converted.zip"
    pdftool.make_zip(paths, str(zip_path))
    g.tool_name = "convert"
    g.output_name = f"{in_path.stem}_converted.zip"
    g.output_path = str(zip_path)
    return send_file(
        str(zip_path), as_attachment=True,
        download_name=f"{in_path.stem}_converted.zip",
        mimetype="application/zip",
    )


@pdf_bp.route("/pdf-to-word", methods=["POST"])
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
    g.tool_name = "pdf-to-word"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=out_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@pdf_bp.route("/split", methods=["POST"])
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
            safe_path = Path(paths[0]).resolve()
            if out_dir.resolve() not in safe_path.parents:
                return jsonify({"error": "invalid output path"}), 400
            g.tool_name = "split"
            g.output_name = safe_path.name
            g.output_path = str(safe_path)
            return send_file(
                str(safe_path), as_attachment=True,
                download_name=safe_path.name,
                mimetype="application/pdf",
            )

        zip_path = OUTPUT_DIR / f"{job_id}_split.zip"
        pdftool.make_zip(paths, str(zip_path))
        g.tool_name = "split"
        g.output_name = f"{in_path.stem}_split.zip"
        g.output_path = str(zip_path)
        return send_file(
            str(zip_path), as_attachment=True,
            download_name=f"{in_path.stem}_split.zip",
            mimetype="application/zip",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# NEW: Video to Images route
@pdf_bp.route("/lock", methods=["POST"])
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

    g.tool_name = "lock"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# NEW: Unlock/Decrypt PDF
@pdf_bp.route("/unlock", methods=["POST"])
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

    g.tool_name = "unlock"
    g.output_name = out_name
    g.output_path = str(out_path)
    return send_file(
        str(out_path), as_attachment=True,
        download_name=out_name,
        mimetype="application/pdf",
    )


# ─────────────────────────────────────────────────────────────
# DOC SCANNER routes
# ─────────────────────────────────────────────────────────────
