"""
docscanner.py — Clean public API for the document scanner.

Re-exports the key functions from pdftool_scan so app.py
(or any other caller) can just do:

    import docscanner
    docscanner.scan(in_path, out_path, filter="bw")
    docscanner.build_pdf(page_paths, out_path)
    docscanner.build_docx(page_paths, out_path, ocr=True)
"""

from pdftool_scan import (
    process_scan,
    images_to_pdf_simple,
    images_to_docx,
    ocr_available,
    ocr_image,
)


# ── Convenience aliases ──────────────────────────────────────

def scan(input_path, output_path, *, perspective=False,
         filter="magic_color", brightness=1.0, contrast=1.0,
         sharpness=1.0, rotate=0, crop=None):
    """Process a single scanned image through the full pipeline."""
    return process_scan(
        input_path, output_path,
        perspective=perspective,
        filter_name=filter,
        brightness=brightness,
        contrast=contrast,
        sharpness=sharpness,
        rotate=rotate,
        crop=crop,
    )


def build_pdf(page_paths, output_path):
    """Stitch scanned page images into a single PDF."""
    return images_to_pdf_simple(page_paths, output_path)


def build_docx(page_paths, output_path, *, ocr=True, lang="eng"):
    """Build a DOCX from scanned pages (with optional OCR)."""
    return images_to_docx(page_paths, output_path,
                          ocr_lang=lang, use_ocr=ocr)


def has_ocr():
    """Check whether Tesseract OCR is available on this system."""
    return ocr_available()
