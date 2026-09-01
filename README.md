# PDFTool Suite

A powerful, all-in-one web-based document, image, video, and scan processing toolkit built with Flask. PDFTool Suite provides a clean web interface and RESTful API endpoints for merging, compressing, converting, splitting, watermarking, encrypting PDFs, extracting video frames, building scanned documents with OCR, and generating QR codes.

---

## Features

### PDF Operations
| Feature | Description |
|---------|-------------|
| **Merge PDFs** | Combine multiple PDFs and images into a single PDF |
| **Compress PDF** | Reduce file size using native or rasterized compression with quality control |
| **PDF ↔ Images** | Convert PDF pages to PNG/JPG/WebP or stitch images into a PDF |
| **PDF to Word** | Convert PDF documents to editable DOCX format |
| **Split PDF** | Split by custom page ranges or fixed-size chunks |
| **Text Watermark** | Add tiled diagonal text watermarks with custom font, color, opacity, and angle |
| **Image Watermark** | Overlay a logo or image watermark at configurable position and scale |
| **Lock / Encrypt** | Password-protect PDFs with 128-bit encryption and granular permissions |
| **Unlock / Decrypt** | Remove passwords and encryption from PDFs |

### Image Operations
| Feature | Description |
|---------|-------------|
| **Compress Images** | Reduce image file size with adjustable quality and max dimensions |
| **Convert Images** | Change format between PNG, JPG, WebP, TIFF, BMP, and GIF |

### Video Operations
| Feature | Description |
|---------|-------------|
| **Video to Images** | Extract frames at custom FPS or max frame count (PNG/JPG/WebP) |
| **Video to PDF** | Convert video frames directly into a single PDF |
| **Video to MP3** | Extract audio track from any video file to MP3 |

### Document Scanner
| Feature | Description |
|---------|-------------|
| **Auto Perspective** | Automatic edge detection and perspective correction |
| **Filters** | Original, B&W, Grayscale, Magic Color, Enhanced, Sharpen |
| **Adjustments** | Brightness, contrast, sharpness, rotation |
| **Manual Crop** | Pixel-precise cropping with coordinate input |
| **OCR** | Optional Tesseract OCR to extract text and build searchable DOCX |
| **Multi-page Export** | Build PDF or DOCX from multiple scanned page images |

### Utilities
| Feature | Description |
|---------|-------------|
| **QR Code Generator** | Generate customizable QR codes with logo overlay support |

---

## Tech Stack

- **Backend:** Flask 3.x, Gunicorn
- **PDF Engine:** pypdf, pypdfium2, pdf2docx, reportlab
- **Image Processing:** Pillow, OpenCV (headless), NumPy
- **OCR:** pytesseract + Tesseract (optional)
- **Video/Audio:** ffmpeg (external binary required)
- **QR Codes:** qrcode[pil]
- **Document Builder:** python-docx

---

## Installation

### Prerequisites
- Python 3.10+
- ffmpeg installed and available in `PATH`
- (Optional) Tesseract OCR for text extraction in scanner

### 1. Clone & Setup

```bash
git clone <repo-url>
cd pdftool-suite
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Development Server

```bash
python app.py
```

The app starts on `http://localhost:8080` by default.

### 3. Production Deployment

```bash
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

---

## API Reference

All endpoints accept `multipart/form-data` POST requests. File downloads are returned as attachments.

### PDF Endpoints

| Endpoint | Form Fields | Description |
|----------|-------------|-------------|
| `POST /merge` | `files` (multiple) | Merge PDFs and images |
| `POST /compress` | `file`, `quality`, `max_dimension`, `dpi`, `mode` | Compress PDF or image |
| `POST /convert` | `file`, `format`, `quality`, `dpi` | Convert between formats |
| `POST /pdf-to-word` | `file` | PDF → DOCX |
| `POST /images-to-pdf` | `files` (multiple images) | Images → PDF |
| `POST /split` | `file`, `split_type`, `ranges` / `pages_per_chunk` | Split PDF |
| `POST /watermark-text` | `file`, `text`, `font_size`, `opacity`, `color`, `angle`, `spacing` | Add text watermark |
| `POST /watermark-image` | `file`, `image`, `opacity`, `position`, `scale` | Add image watermark |
| `POST /lock` | `file`, `user_password`, `owner_password`, `allow_*` | Encrypt PDF |
| `POST /unlock` | `file`, `password` | Decrypt PDF |

### Video Endpoints

| Endpoint | Form Fields | Description |
|----------|-------------|-------------|
| `POST /video-to-images` | `file`, `format`, `quality`, `fps`, `max_frames` | Extract frames as ZIP |
| `POST /video-to-pdf` | `file`, `quality`, `fps`, `max_frames`, `max_dimension` | Video → PDF |
| `POST /video-to-mp3` | `file`, `bitrate` | Extract audio to MP3 |

### Scanner Endpoints

| Endpoint | Form Fields | Description |
|----------|-------------|-------------|
| `GET /scan/health` | — | Check OCR availability |
| `POST /scan/process` | `file`, `perspective`, `filter`, `brightness`, `contrast`, `sharpness`, `rotate`, `crop_*` | Process a single scan image |
| `POST /scan/build` | `files` (multiple), `ocr`, `ocr_lang`, `format` | Build PDF or DOCX from scan pages |

### Utility Endpoints

| Endpoint | Form Fields | Description |
|----------|-------------|-------------|
| `POST /qr-generate` | `data`, `box_size`, `border`, `fill_color`, `back_color`, `error_correction`, `logo` | Generate QR code PNG |
| `GET /health` | — | Service health check |

---

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Server listen port |
| `MAX_CONTENT_LENGTH` | `500 MB` | Maximum upload size (configured in app) |

---

## File Structure

```
.
├── app.py              # Flask application & routes
├── pdftool.py          # Core PDF/image/video processing engine
├── pdftool_scan.py     # Document scanner & OCR pipeline
├── pdftool_video.py    # Video/audio extraction helpers
├── requirements.txt    # Python dependencies
├── uploads/            # Temporary upload storage (auto-cleaned)
├── outputs/            # Generated file output directory
└── templates/
    └── index.html      # Main web UI
```

---

## Notes

- **Auto-cleanup:** Files older than 1 hour in `uploads/` and `outputs/` are automatically purged on each homepage visit.
- **Encryption:** Lock/Unlock uses pypdf with 128-bit RC4/AES encryption. Some advanced PDF encryption schemes may not be supported.
- **OCR:** Scanner OCR requires the `tesseract` binary to be installed on the host system. If unavailable, the scanner falls back to image-based DOCX generation.
- **ffmpeg:** Video processing routes require `ffmpeg` to be installed and accessible in the system `PATH`.
- **Watermarking:** Watermark pages are rendered on US Letter size (612×792 pts). For best results with non-standard page sizes, the watermark is centered and scaled proportionally.

---

## License

MIT License — feel free to use, modify, and distribute.
