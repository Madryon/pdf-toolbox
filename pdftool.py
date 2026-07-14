import io
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from PIL import Image
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}
PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".mpeg", ".mpg", ".3gp"}


def _to_rgb(img):
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def _resize(img, max_dimension):
    if max_dimension and (img.width > max_dimension or img.height > max_dimension):
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    return img


def _save_image(img, output_path, quality=60, fmt=None):
    if fmt is None:
        fmt = Path(output_path).suffix.lstrip(".").upper() or "PNG"
    fmt = fmt.upper()
    if fmt in ("JPG", "JPEG"):
        img = _to_rgb(img)
        img.save(output_path, "JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt == "PNG":
        img.save(output_path, "PNG", optimize=True)
    elif fmt == "WEBP":
        img.save(output_path, "WEBP", quality=quality, method=6)
    elif fmt == "TIFF":
        img.save(output_path, "TIFF", compression="tiff_lzw")
    else:
        if fmt in ("BMP",):
            img = _to_rgb(img)
        img.save(output_path, fmt, optimize=True)


def merge_pdfs(input_paths, output_path):
    pdf_paths = []
    image_paths = []
    for path in input_paths:
        ext = Path(path).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            image_paths.append(path)
        elif ext in PDF_EXTENSIONS:
            pdf_paths.append(path)
        else:
            raise ValueError(f"unsupported input file: {path}")
    writer = PdfWriter()
    if image_paths:
        tmp = output_path + f".imgs_{uuid.uuid4().hex}.pdf"
        try:
            images_to_pdf(image_paths, tmp)
            for page in PdfReader(tmp).pages:
                writer.add_page(page)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    for path in pdf_paths:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError(f"encrypted PDF not supported: {path}")
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def images_to_pdf(input_paths, output_path):
    images = []
    for p in input_paths:
        img = Image.open(p)
        img.load()
        img = _to_rgb(img)
        images.append(img)
    if not images:
        raise ValueError("no images provided")
    first, *rest = images
    first.save(output_path, "PDF", save_all=True, append_images=rest, resolution=150.0)
    return output_path


def pdf_to_images(input_path, output_dir, fmt="png", dpi=150, quality=85):
    pdf = pdfium.PdfDocument(input_path)
    scale = dpi / 72
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        out_path = output_dir / f"page_{i + 1:04d}.{fmt}"
        _save_image(pil_image, str(out_path), quality=quality, fmt=fmt)
        paths.append(str(out_path))
    return paths


def compress_image(input_path, output_path, quality=60, max_dimension=None):
    img = Image.open(input_path)
    img.load()
    img = _resize(img, max_dimension)
    _save_image(img, output_path, quality=quality)
    return output_path


def compress_pdf(input_path, output_path, quality=60, max_dimension=1600, dpi=120, mode="auto"):
    if mode == "rasterize":
        return _compress_pdf_rasterize(input_path, output_path, quality, max_dimension, dpi)
    if mode == "native":
        return _compress_pdf_native(input_path, output_path, quality, max_dimension)
    try:
        return _compress_pdf_native(input_path, output_path, quality, max_dimension)
    except Exception:
        return _compress_pdf_rasterize(input_path, output_path, quality, max_dimension, dpi)


def _compress_pdf_native(input_path, output_path, quality=60, max_dimension=1600):
    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for page in writer.pages:
        try:
            for img in page.images:
                try:
                    pil_img = img.image
                    pil_img = _to_rgb(pil_img)
                    pil_img = _resize(pil_img, max_dimension)
                    img.replace(pil_img, quality=quality)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            page.compress_content_streams()
        except Exception:
            pass
        try:
            for fn in page.inline_images:
                pass
        except Exception:
            pass
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def _compress_pdf_rasterize(input_path, output_path, quality=60, max_dimension=1600, dpi=120):
    pdf = pdfium.PdfDocument(input_path)
    scale = dpi / 72
    images = []
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        pil_image = _to_rgb(pil_image)
        pil_image = _resize(pil_image, max_dimension)
        images.append(pil_image)
    if not images:
        raise ValueError("PDF has no pages")
    first, *rest = images
    tmp_img_dir = output_path + f".imgs_{uuid.uuid4().hex}"
    try:
        Path(tmp_img_dir).mkdir(parents=True, exist_ok=True)
        tmp_paths = []
        for idx, im in enumerate(images, start=1):
            tp = os.path.join(tmp_img_dir, f"p_{idx:04d}.jpg")
            _save_image(im, tp, quality=quality, fmt="jpg")
            tmp_paths.append(tp)
        imgs = [Image.open(p) for p in tmp_paths]
        imgs[0].save(output_path, "PDF", save_all=True, append_images=imgs[1:], resolution=72.0)
    finally:
        shutil.rmtree(tmp_img_dir, ignore_errors=True)
    return output_path


def convert_image(input_path, output_path, quality=90):
    img = Image.open(input_path)
    img.load()
    _save_image(img, output_path, quality=quality)
    return output_path


def convert_file(input_path, output_path, quality=85, dpi=150):
    in_ext = Path(input_path).suffix.lower()
    out_ext = Path(output_path).suffix.lower()
    out_path = Path(output_path)
    if in_ext == ".pdf" and out_ext in IMAGE_EXTENSIONS:
        out_dir = out_path.parent if str(out_path.parent) else Path(".")
        fmt = out_ext.lstrip(".")
        paths = pdf_to_images(input_path, str(out_dir), fmt=fmt, dpi=dpi, quality=quality)
        if len(paths) == 1:
            os.replace(paths[0], output_path)
            return [output_path]
        return paths
    if in_ext in IMAGE_EXTENSIONS and out_ext == ".pdf":
        images_to_pdf([input_path], output_path)
        return [output_path]
    if in_ext in IMAGE_EXTENSIONS and out_ext in IMAGE_EXTENSIONS:
        convert_image(input_path, output_path, quality=quality)
        return [output_path]
    raise ValueError(f"unsupported conversion: {in_ext} -> {out_ext}")


def pdf_to_word(input_path, output_path):
    from pdf2docx import Converter
    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported")
    cv = Converter(input_path)
    try:
        cv.convert(output_path)
    finally:
        cv.close()
    return output_path


# ─────────────────────────────────────────────────────────────
# NEW: Split PDF functions
# ─────────────────────────────────────────────────────────────

def split_pdf_by_pages(input_path, output_dir, page_ranges):
    """
    Split a PDF by specific page ranges.
    page_ranges: list of tuples like [(1,3), (4,7), (8,10)] or [(1,3), (4,None)]
    Returns list of output paths.
    """
    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported")

    total_pages = len(reader.pages)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for idx, (start, end) in enumerate(page_ranges, start=1):
        # Convert to 0-based indexing
        start_idx = max(0, start - 1)
        if end is None or end > total_pages:
            end_idx = total_pages
        else:
            end_idx = end

        if start_idx >= end_idx:
            continue

        writer = PdfWriter()
        for i in range(start_idx, end_idx):
            writer.add_page(reader.pages[i])

        out_path = output_dir / f"split_{idx:03d}_pages_{start}-{end if end else 'end'}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        paths.append(str(out_path))

    return paths


def split_pdf_by_chunks(input_path, output_dir, pages_per_chunk):
    """
    Split a PDF into chunks of N pages each.
    Returns list of output paths.
    """
    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported")

    total_pages = len(reader.pages)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    chunk_num = 1
    for start in range(0, total_pages, pages_per_chunk):
        end = min(start + pages_per_chunk, total_pages)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])

        out_path = output_dir / f"split_{chunk_num:03d}_pages_{start+1}-{end}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        paths.append(str(out_path))
        chunk_num += 1

    return paths


# ─────────────────────────────────────────────────────────────
# NEW: Video to Images / PDF functions
# ─────────────────────────────────────────────────────────────

def _ffmpeg_bin():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(
            "ffmpeg is not installed on the server. "
            "Make sure ffmpeg is available in the deploy environment (nixpacks.toml)."
        )
    return ffmpeg


def _quality_to_ffmpeg_qscale(quality):
    """Map a 1-100 'quality' knob to ffmpeg's -q:v scale (2=best, 31=worst)."""
    quality = max(1, min(100, int(quality)))
    return max(2, round(31 - (quality / 100) * 29))


def _extract_frames_ffmpeg(input_path, output_dir, fmt="png", quality=85,
                            max_frames=None, fps=None, max_dimension=None):
    """
    Extract frames from a video using ffmpeg directly (native C decode + filter,
    only touches the frames actually being kept -- much faster than reading
    every frame in a Python loop).
    """
    ffmpeg = _ffmpeg_bin()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    vf_parts = []
    if fps and fps > 0:
        vf_parts.append(f"fps={fps}")
    if max_dimension:
        vf_parts.append(
            f"scale='if(gt(iw,ih),min({max_dimension},iw),-2)':"
            f"'if(gt(iw,ih),-2,min({max_dimension},ih))'"
        )

    ext = "jpg" if fmt in ("jpg", "jpeg") else fmt
    out_pattern = str(output_dir / f"frame_%04d.{ext}")

    cmd = [ffmpeg, "-y", "-i", str(input_path)]
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    if ext in ("jpg", "webp"):
        cmd += ["-q:v", str(_quality_to_ffmpeg_qscale(quality))]
    if max_frames:
        cmd += ["-frames:v", str(max_frames)]
    cmd += [out_pattern]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore")[-1500:]
        raise ValueError(f"ffmpeg failed to extract frames: {stderr}")

    paths = sorted(str(p) for p in output_dir.glob(f"frame_*.{ext}"))
    if not paths:
        raise ValueError("No frames could be extracted from video")
    return paths


def video_to_frames(input_path, output_dir, fmt="png", quality=85, max_frames=None, fps=10):
    """
    Extract frames from a video file (ffmpeg-backed, fast).

    Args:
        input_path: path to video file
        output_dir: directory to save frames
        fmt: output image format (png, jpg, webp)
        quality: image quality for lossy formats
        max_frames: maximum number of frames to extract (None = all)
        fps: extract at this FPS (None = original video FPS, i.e. every frame)

    Returns:
        list of output file paths
    """
    return _extract_frames_ffmpeg(
        input_path, output_dir, fmt=fmt, quality=quality,
        max_frames=max_frames, fps=fps,
    )


def video_to_pdf(input_path, output_path, quality=75, max_frames=None, fps=10, max_dimension=None):
    """
    Convert video frames to a single PDF (ffmpeg-backed, fast).

    Args:
        input_path: path to video file
        output_path: path for output PDF
        quality: JPEG quality for frames in PDF
        max_frames: maximum frames to include
        fps: target FPS for extraction
        max_dimension: resize frames if larger than this
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        frame_paths = _extract_frames_ffmpeg(
            input_path, tmp_dir, fmt="jpg", quality=quality,
            max_frames=max_frames, fps=fps, max_dimension=max_dimension,
        )

        images = [_to_rgb(Image.open(p)) for p in frame_paths]
        first, *rest = images
        first.save(output_path, "PDF", save_all=True, append_images=rest,
                    resolution=72.0, quality=quality)

    return output_path




def add_text_watermark(input_path, output_path, text="CONFIDENTIAL", font_size=60, opacity=0.3, color=(128,128,128), angle=45, spacing=200):
    """
    Add text watermark to every page of a PDF.

    Args:
        input_path: path to input PDF
        output_path: path for output PDF
        text: watermark text
        font_size: font size in points
        opacity: opacity 0.0-1.0
        color: RGB tuple (r,g,b)
        angle: rotation angle in degrees
        spacing: spacing between watermarks
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    import io

    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported - unlock first")

    writer = PdfWriter()

    # Create watermark PDF page
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica-Bold", font_size)

    r, g, b = color
    can.setFillColorRGB(r/255, g/255, b/255, alpha=opacity)
    can.setStrokeColorRGB(r/255, g/255, b/255, alpha=opacity)

    # Draw text multiple times across page
    page_width, page_height = letter
    can.saveState()
    can.translate(page_width/2, page_height/2)
    can.rotate(angle)

    # Draw text in grid pattern
    for x in range(-int(page_width), int(page_width)+1, spacing):
        for y in range(-int(page_height), int(page_height)+1, spacing):
            can.drawString(x, y, text)

    can.restoreState()
    can.save()
    packet.seek(0)

    watermark_pdf = PdfReader(packet)
    watermark_page = watermark_pdf.pages[0]

    # Apply watermark to each page
    for page in reader.pages:
        page.merge_page(watermark_page, over=True)
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def add_image_watermark(input_path, output_path, image_path, opacity=0.3, position="center", scale=0.3):
    """
    Add image watermark to every page of a PDF.

    Args:
        input_path: path to input PDF
        output_path: path for output PDF
        image_path: path to watermark image (PNG with transparency preferred)
        opacity: opacity 0.0-1.0
        position: "center", "top-left", "top-right", "bottom-left", "bottom-right", "tile"
        scale: scale factor relative to page width
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from PIL import Image
    import io

    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported - unlock first")

    writer = PdfWriter()

    # Get image dimensions
    img = Image.open(image_path)
    img_w, img_h = img.size

    # Create watermark PDF
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    page_width, page_height = letter

    # Calculate size
    target_width = page_width * scale
    target_height = (img_h / img_w) * target_width

    # Position
    if position == "center":
        x = (page_width - target_width) / 2
        y = (page_height - target_height) / 2
    elif position == "top-left":
        x, y = 20, page_height - target_height - 20
    elif position == "top-right":
        x, y = page_width - target_width - 20, page_height - target_height - 20
    elif position == "bottom-left":
        x, y = 20, 20
    elif position == "bottom-right":
        x, y = page_width - target_width - 20, 20
    else:
        x = (page_width - target_width) / 2
        y = (page_height - target_height) / 2

    can.setFillAlpha(opacity)
    can.drawImage(image_path, x, y, width=target_width, height=target_height, mask="auto")
    can.save()
    packet.seek(0)

    watermark_pdf = PdfReader(packet)
    watermark_page = watermark_pdf.pages[0]

    for page in reader.pages:
        page.merge_page(watermark_page, over=True)
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def lock_pdf(input_path, output_path, user_password="", owner_password="", 
             allow_printing=True, allow_copying=True, allow_modifying=False, 
             allow_annotating=False, allow_form_filling=False):
    """
    Encrypt and password-protect a PDF with security settings.

    Args:
        input_path: path to input PDF
        output_path: path for output PDF
        user_password: password required to open PDF (empty = no open password)
        owner_password: password for permissions (if empty, uses user_password)
        allow_printing: allow printing
        allow_copying: allow copying text/images
        allow_modifying: allow modifying content
        allow_annotating: allow adding annotations
        allow_form_filling: allow filling forms
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(input_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted PDF not supported - unlock first")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    # Build permissions
    permissions = 0
    if allow_printing:
        permissions |= 1 << 2  # Print
    if allow_modifying:
        permissions |= 1 << 3  # Modify
    if allow_copying:
        permissions |= 1 << 4  # Copy
    if allow_annotating:
        permissions |= 1 << 5  # Annotate
    if allow_form_filling:
        permissions |= 1 << 8  # Fill forms

    # Encrypt
    owner = owner_password if owner_password else user_password
    writer.encrypt(
        user_password=user_password,
        owner_password=owner,
        use_128bit=True,
        permissions=permissions
    )

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def unlock_pdf(input_path, output_path, password=""):
    """
    Remove password and encryption from a PDF.

    Args:
        input_path: path to encrypted PDF
        output_path: path for output decrypted PDF
        password: password to decrypt (try empty first)
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(input_path)

    if not reader.is_encrypted:
        # Not encrypted, just copy
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        return output_path

    # Try to decrypt
    decrypted = False
    if password:
        try:
            reader.decrypt(password)
            decrypted = True
        except Exception:
            pass

    if not decrypted:
        try:
            reader.decrypt("")
            decrypted = True
        except Exception:
            pass

    if not decrypted:
        raise ValueError("Could not decrypt PDF - wrong password or unsupported encryption")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def make_zip(paths_or_dir, zip_path):
    paths = []
    if isinstance(paths_or_dir, (list, tuple)):
        paths = list(paths_or_dir)
    else:
        p = Path(paths_or_dir)
        if p.is_dir():
            paths = sorted([str(x) for x in p.iterdir() if x.is_file()])
        else:
            paths = [str(p)]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for fp in paths:
            z.write(fp, Path(fp).name)
    return zip_path


def build_parser():
    import argparse
    parser = argparse.ArgumentParser(description="PDF merger, compressor and file converter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("inputs", nargs="+")
    merge_parser.add_argument("-o", "--output", required=True)
    compress_parser = subparsers.add_parser("compress")
    compress_parser.add_argument("input")
    compress_parser.add_argument("-o", "--output", required=True)
    compress_parser.add_argument("-q", "--quality", type=int, default=60)
    compress_parser.add_argument("-m", "--max-dimension", type=int, default=1600)
    compress_parser.add_argument("--dpi", type=int, default=120)
    compress_parser.add_argument("--mode", choices=["auto", "native", "rasterize"], default="auto")
    convert_parser = subparsers.add_parser("convert")
    convert_parser.add_argument("input")
    convert_parser.add_argument("-o", "--output", required=True)
    convert_parser.add_argument("-q", "--quality", type=int, default=85)
    convert_parser.add_argument("--dpi", type=int, default=150)
    word_parser = subparsers.add_parser("pdf-to-word")
    word_parser.add_argument("input")
    word_parser.add_argument("-o", "--output", required=True)

    # NEW CLI parsers
    split_parser = subparsers.add_parser("split")
    split_parser.add_argument("input")
    split_parser.add_argument("-o", "--output-dir", required=True)
    split_parser.add_argument("--by-pages", help="Page ranges like 1-3,4-7,8-10")
    split_parser.add_argument("--by-chunks", type=int, help="Pages per chunk")

    video_parser = subparsers.add_parser("video-to-images")
    video_parser.add_argument("input")
    video_parser.add_argument("-o", "--output-dir", required=True)
    video_parser.add_argument("--format", default="png", choices=["png", "jpg", "webp"])
    video_parser.add_argument("--quality", type=int, default=85)
    video_parser.add_argument("--fps", type=float, help="Target FPS")
    video_parser.add_argument("--max-frames", type=int, help="Max frames to extract")

    video_pdf_parser = subparsers.add_parser("video-to-pdf")
    video_pdf_parser.add_argument("input")
    video_pdf_parser.add_argument("-o", "--output", required=True)
    video_pdf_parser.add_argument("--quality", type=int, default=75)
    video_pdf_parser.add_argument("--fps", type=float)
    video_pdf_parser.add_argument("--max-frames", type=int)
    video_pdf_parser.add_argument("--max-dimension", type=int)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "merge":
        merge_pdfs(args.inputs, args.output)
        print(f"merged {len(args.inputs)} files into {args.output}")
    elif args.command == "compress":
        ext = Path(args.input).suffix.lower()
        if ext == ".pdf":
            compress_pdf(args.input, args.output, quality=args.quality, max_dimension=args.max_dimension, dpi=args.dpi, mode=args.mode)
        elif ext in IMAGE_EXTENSIONS:
            compress_image(args.input, args.output, quality=args.quality, max_dimension=args.max_dimension)
        else:
            print(f"unsupported file type for compression: {ext}")
            sys.exit(1)
        before = os.path.getsize(args.input)
        after = os.path.getsize(args.output)
        ratio = (1 - after / before) * 100 if before else 0
        print(f"{args.input}: {before} bytes -> {args.output}: {after} bytes ({ratio:.1f}% smaller)")
    elif args.command == "convert":
        paths = convert_file(args.input, args.output, quality=args.quality, dpi=args.dpi)
        print(f"converted {args.input} -> {len(paths)} output file(s)")
    elif args.command == "pdf-to-word":
        pdf_to_word(args.input, args.output)
        print(f"converted {args.input} -> {args.output}")
    elif args.command == "split":
        if args.by_pages:
            ranges = []
            for part in args.by_pages.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    start = int(a)
                    end = int(b) if b else None
                    ranges.append((start, end))
                else:
                    p = int(part)
                    ranges.append((p, p))
            paths = split_pdf_by_pages(args.input, args.output_dir, ranges)
            print(f"split into {len(paths)} files")
        elif args.by_chunks:
            paths = split_pdf_by_chunks(args.input, args.output_dir, args.by_chunks)
            print(f"split into {len(paths)} chunks of {args.by_chunks} pages")
        else:
            print("specify --by-pages or --by-chunks")
            sys.exit(1)
    elif args.command == "video-to-images":
        paths = video_to_frames(args.input, args.output_dir, fmt=args.format, quality=args.quality, 
                                max_frames=args.max_frames, fps=args.fps)
        print(f"extracted {len(paths)} frames to {args.output_dir}")
    elif args.command == "video-to-pdf":
        video_to_pdf(args.input, args.output, quality=args.quality, max_frames=args.max_frames,
                     fps=args.fps, max_dimension=args.max_dimension)
        print(f"converted video to {args.output}")


if __name__ == "__main__":
    main()
