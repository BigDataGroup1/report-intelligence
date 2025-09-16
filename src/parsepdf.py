#!/usr/bin/env python
"""
Lab 1 parser (no argparse, fully commented):
- Always processes: data/raw/Apple_SEA.pdf
- Extracts words with pdfplumber (digital text).
- Falls back to OCR (Tesseract) for pages with too little text.
- Saves one JSON line per word to: data/parsed/json/words/APPLE_SEA.jsonl
"""

import json, os
from pathlib import Path

import pdfplumber                  # digital text extraction
from rich import print             # colored console messages

# OCR stack (no Poppler needed)
import fitz                        # PyMuPDF: render PDF pages to images
import pytesseract                 # wrapper for Tesseract binary
from PIL import Image              # Pillow: handle images
import numpy as np                 # convert images to arrays for OCR

# -------- Hard-coded config --------
PDF_PATH = Path("data/raw/Apple_SEA.pdf")               # input PDF
FILE_ID = "APPLE_SEA"                                   # output ID
OUTDIR = Path("data/parsed/json/words")                 # output folder
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # Windows path; "" if Tesseract is already in PATH

MIN_WORDS = 10         # if pdfplumber finds fewer words -> OCR
MIN_CHARS = 50         # if pdfplumber finds fewer chars -> OCR
DPI = 300              # rendering DPI for OCR (higher -> sharper but slower)
LANG = "eng"           # OCR language(s) for Tesseract

# ------------------------------------------------------------

def normalize_bbox(x0, y0, x1, y1, width, height, origin):
    """
    Normalize a box into [0..1] coordinates, always using TOP-LEFT origin.
    """
    nx0, nx1 = x0/width, x1/width
    if origin == "top-left":
        ny0, ny1 = y0/height, y1/height
    elif origin == "bottom-left":
        # flip vertical direction for bottom-left coords
        ny0 = 1.0 - (y1/height)
        ny1 = 1.0 - (y0/height)
    else:
        raise ValueError(f"Unknown origin: {origin}")
    return {"x0": nx0, "y0": ny0, "x1": nx1, "y1": ny1}

def write_word(out_f, file_id, page_num, text, bbox_norm, source, conf=None):
    """
    Write one word record as a JSON line.
    """
    out_f.write(json.dumps({
        "file_id": file_id,      # logical ID (here: APPLE_SEA)
        "page": page_num,        # page number (1-based)
        "word": text,            # the actual word text
        "bbox_norm": bbox_norm,  # normalized bounding box
        "source": source,        # "pdfplumber" or "ocr"
        "conf": conf             # OCR confidence (if available)
    }, ensure_ascii=False) + "\n")

def extract_pdfplumber_words(page, file_id, pagenum, out_f):
    """
    Try extracting words with pdfplumber for one page.
    If too few words/chars are found, flag the page for OCR.
    """
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    text_len = sum(len((w.get("text") or "")) for w in words)
    needs_ocr = (len(words) < MIN_WORDS) or (text_len < MIN_CHARS)
    if needs_ocr:
        return 0, True

    pw, ph = page.width, page.height
    count = 0
    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue
        x0, x1 = w["x0"], w["x1"]
        y0, y1 = w["top"], w["bottom"]
        bbox_norm = normalize_bbox(x0, y0, x1, y1, pw, ph, origin="top-left")
        write_word(out_f, file_id, pagenum, t, bbox_norm, "pdfplumber", None)
        count += 1
    return count, False

def ocr_pages_with_pymupdf(pdf_path: Path, file_id: str, out_f, pages_to_do, dpi_like=DPI, lang=LANG):
    """
    OCR the subset of pages listed in 'pages_to_do'.
    """
    # If Tesseract path is provided, set it
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    zoom = dpi_like / 72.0
    mat = fitz.Matrix(zoom, zoom)
    doc = fitz.open(str(pdf_path))

    for pagenum in pages_to_do:
        page = doc[pagenum - 1]
        # Render the page to an image
        pix = page.get_pixmap(matrix=mat, alpha=False)
        width, height = pix.width, pix.height
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        arr = np.array(img)

        # Run Tesseract OCR to get word-level results
        data = pytesseract.image_to_data(arr, lang=lang, output_type=pytesseract.Output.DICT)
        for i in range(len(data["text"])):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            x0, y0, x1, y1 = x, y, x + w, y + h
            bbox_norm = normalize_bbox(x0, y0, x1, y1, width, height, origin="top-left")
            try:
                conf = float(data["conf"][i]); conf = conf if conf >= 0 else None
            except:
                conf = None
            write_word(out_f, file_id, pagenum, text, bbox_norm, "ocr", conf)

def parse_pdf(pdf_path: Path, file_id: str, out_path: Path):
    """
    Main routine:
    1. Try pdfplumber on each page.
    2. If page looks empty, add it to 'needs_ocr_pages'.
    3. OCR those pages with PyMuPDF + Tesseract.
    """
    needs_ocr_pages = []
    with pdfplumber.open(str(pdf_path)) as pdf, open(out_path, "w", encoding="utf-8") as out_f:
        for pagenum, page in enumerate(pdf.pages, start=1):
            _, needs_ocr = extract_pdfplumber_words(page, file_id, pagenum, out_f)
            if needs_ocr:
                needs_ocr_pages.append(pagenum)

    # OCR pass for flagged pages
    if needs_ocr_pages:
        with open(out_path, "a", encoding="utf-8") as out_f:
            ocr_pages_with_pymupdf(pdf_path, file_id, out_f, needs_ocr_pages)

# ---------------- Run directly ----------------
if __name__ == "__main__":
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTDIR / f"{FILE_ID}.jsonl"

    print(f"[cyan]Parsing →[/] {PDF_PATH}")
    parse_pdf(PDF_PATH, FILE_ID, out_path)
    print(f"[green]Done![/] JSONL saved at {out_path}")
