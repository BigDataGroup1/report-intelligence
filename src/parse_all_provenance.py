
from pathlib import Path
import json
import pdfplumber
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import numpy as np
import pandas as pd

# ---------------- Config ----------------
IN_DIR = Path("data/upload")
OUT_ROOT = Path("data/parsed")
MIN_WORDS = 10        # trigger OCR if fewer words
MIN_CHARS = 50        # or too few characters
DPI = 300             # render DPI for OCR (higher = slower, better)
LANG = "eng"          # Tesseract lang
TESSERACT_CMD = ""    # Windows: r"C:\Program Files\Tesseract-OCR\tesseract.exe" (leave "" if in PATH)

# -------------- Helpers -----------------
def ensure_dirs(out_base: Path):
    (out_base / "pages").mkdir(parents=True, exist_ok=True)
    (out_base / "tables").mkdir(parents=True, exist_ok=True)
    out_base.mkdir(parents=True, exist_ok=True)

def normalize_bbox(x0, y0, x1, y1, width, height, origin="top-left"):
    nx0, nx1 = x0 / width, x1 / width
    if origin == "top-left":
        ny0, ny1 = y0 / height, y1 / height
    else:
        # bottom-left -> flip
        ny0 = 1.0 - (y1 / height)
        ny1 = 1.0 - (y0 / height)
    return {"x0": nx0, "y0": ny0, "x1": nx1, "y1": ny1}

def write_word(out_f, file_id, page_num, text, bbox_norm, source, conf=None):
    out_f.write(json.dumps({
        "file_id": file_id,
        "page": page_num,
        "word": text,
        "bbox_norm": bbox_norm,
        "source": source,
        "conf": conf
    }, ensure_ascii=False) + "\n")

def ocr_page_words(pdf_path: Path, page_num: int, dpi=DPI, lang=LANG):
    """Render page with PyMuPDF and OCR with Tesseract -> word boxes + conf."""
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    width, height = pix.width, pix.height
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    arr = np.array(img)
    data = pytesseract.image_to_data(arr, lang=lang, output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        conf = None
        try:
            conf_val = float(data["conf"][i])
            conf = conf_val if conf_val >= 0 else None
        except:
            pass
        words.append((t, x, y, x + w, y + h, width, height, conf))
    return words

def extract_tables_plumber(pdf_path: Path, tables_dir: Path):
    saved = 0
    with pdfplumber.open(pdf_path) as pdf:
        for p_i, page in enumerate(pdf.pages, start=1):
            try:
                tbls = page.extract_tables()
                for t_i, tbl in enumerate(tbls, start=1):
                    df = pd.DataFrame(tbl)
                    # pdfplumber returns headerless matrices; keep raw
                    out_csv = tables_dir / f"table_p{p_i}_{t_i}.csv"
                    df.to_csv(out_csv, index=False, header=False)
                    saved += 1
            except Exception:
                continue
    return saved

# -------------- Main per-PDF ------------
def process_pdf(pdf_path: Path):
    file_id = pdf_path.stem
    out_base = OUT_ROOT / file_id
    ensure_dirs(out_base)
    pages_dir = out_base / "pages"
    tables_dir = out_base / "tables"
    words_jsonl = out_base / f"{file_id}_words.jsonl"
    ocr_log_csv = out_base / "ocr_pages.csv"

    # Text + word-level JSONL (plumber first, OCR fallback)
    ocr_pages = []
    with pdfplumber.open(pdf_path) as pdf, open(words_jsonl, "w", encoding="utf-8") as wf:
        for i, page in enumerate(pdf.pages, start=1):
            # ---- pdfplumber words ----
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            text_len = sum(len((w.get("text") or "")) for w in words)

            # write page-level text file
            page_text = page.extract_text() or ""
            (pages_dir / f"page_{i}.txt").write_text(page_text, encoding="utf-8")

            # Decide if this page needs OCR
            needs_ocr = (len(words) < MIN_WORDS) or (text_len < MIN_CHARS)

            if not needs_ocr:
                # write word-level JSONL from pdfplumber
                pw, ph = page.width, page.height
                for w in words:
                    t = (w.get("text") or "").strip()
                    if not t:
                        continue
                    x0, x1 = w["x0"], w["x1"]
                    y0, y1 = w["top"], w["bottom"]
                    bbox = normalize_bbox(x0, y0, x1, y1, pw, ph, origin="top-left")
                    write_word(wf, file_id, i, t, bbox, "pdfplumber", None)
            else:
                ocr_pages.append(i)

    # OCR pass for flagged pages (word boxes + conf)
    if ocr_pages:
        with open(words_jsonl, "a", encoding="utf-8") as wf:
            for p in ocr_pages:
                for (t, x0, y0, x1, y1, W, H, conf) in ocr_page_words(pdf_path, p):
                    bbox = normalize_bbox(x0, y0, x1, y1, W, H, origin="top-left")
                    write_word(wf, file_id, p, t, bbox, "ocr", conf)

        # Save a simple log of which pages required OCR
        pd.DataFrame({"page": ocr_pages}).to_csv(ocr_log_csv, index=False)

    # Tables via pdfplumber
    saved = extract_tables_plumber(pdf_path, tables_dir)
    print(f"✓ {pdf_path.name}: text → {pages_dir}, words → {words_jsonl}, tables → {saved} CSV(s)")

def main():
    pdfs = sorted(IN_DIR.rglob("*.pdf"))
    if not pdfs:
        print("No PDFs found in data/uploads/. Add a PDF and rerun.")
        return
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for pdf in pdfs:
        process_pdf(pdf)

if __name__ == "__main__":
    main()
