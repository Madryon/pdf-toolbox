import io
import os
import shutil
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

def video_to_frames(input_path, output_dir, fmt="png", quality=85, max_frames=None, fps=None):
    """
    Extract frames from a video file.

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
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {input_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    frame_count = 0
    saved_count = 0

    # Calculate frame skip interval
    if fps and fps > 0 and video_fps > 0:
        skip_interval = max(1, int(round(video_fps / fps)))
    else:
        skip_interval = 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % skip_interval == 0:
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)

            out_path = output_dir / f"frame_{saved_count + 1:04d}.{fmt}"
            _save_image(pil_image, str(out_path), quality=quality, fmt=fmt)
            paths.append(str(out_path))
            saved_count += 1

            if max_frames and saved_count >= max_frames:
                break

        frame_count += 1

    cap.release()
    return paths


def video_to_pdf(input_path, output_path, quality=75, max_frames=None, fps=None, max_dimension=None):
    """
    Convert video frames to a single PDF.

    Args:
        input_path: path to video file
        output_path: path for output PDF
        quality: JPEG quality for frames in PDF
        max_frames: maximum frames to include
        fps: target FPS for extraction
        max_dimension: resize frames if larger than this
    """
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {input_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    images = []
    frame_count = 0
    saved_count = 0

    if fps and fps > 0 and video_fps > 0:
        skip_interval = max(1, int(round(video_fps / fps)))
    else:
        skip_interval = 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % skip_interval == 0:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)
            pil_image = _to_rgb(pil_image)
            if max_dimension:
                pil_image = _resize(pil_image, max_dimension)
            images.append(pil_image)
            saved_count += 1

            if max_frames and saved_count >= max_frames:
                break

        frame_count += 1

    cap.release()

    if not images:
        raise ValueError("No frames could be extracted from video")

    # Save as PDF with JPEG compression for smaller file size
    first, *rest = images
    first.save(output_path, "PDF", save_all=True, append_images=rest, resolution=72.0, quality=quality)
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
