# build_metadata.py

from pathlib import Path
import json
import pandas as pd
import re

PARSED_ROOT = Path("data/parsed")
STAGED_ROOT = Path("data/staged")  # output of Lab 5

# ----------------------------
# Optional PDF parsing helpers
# ----------------------------
import re

UPLOAD_ROOT = Path("data/upload")  # <-- fix: your screenshot shows data/upload

def _extract_pdf_text_first_pages(pdf_path: Path, max_pages: int = 2) -> str:
    """Try PyPDF2 (or pypdf) to read first pages; return '' if anything fails."""
    txts = []
    try:
        import PyPDF2  # try PyPDF2
        with pdf_path.open("rb") as fh:
            r = PyPDF2.PdfReader(fh)
            for i in range(min(max_pages, len(r.pages))):
                try:
                    txts.append(r.pages[i].extract_text() or "")
                except Exception:
                    txts.append("")
    except Exception:
        # fallback to pypdf if installed under the new name
        try:
            import pypdf
            with pdf_path.open("rb") as fh:
                r = pypdf.PdfReader(fh)
                for i in range(min(max_pages, len(r.pages))):
                    try:
                        txts.append(r.pages[i].extract_text() or "")
                    except Exception:
                        txts.append("")
        except Exception:
            return ""
    return "\n".join(txts).strip()

_RX_FY_DATE = re.compile(r"fiscal\s+year\s+ended\s+([A-Za-z]+\s+\d{1,2},\s+(?:19|20)\d{2})", re.I)
_RX_COMPANY = re.compile(r"^\s*([A-Z][A-Za-z0-9&\.\-,'\s]+?(?:Inc\.?|Incorporated|Corporation|Corp\.?|Ltd\.?))\s*$", re.M)

def extract_company_fy(pdf_path: Path, pages_dir: Path, doc_id: str):
    """
    Build a combined text corpus from:
      1) first 2 pages of the PDF (if present),
      2) parsed text files pages/page_1.txt and page_2.txt (if present).
    Then regex out: company, fiscal_year_date, fiscal_year.
    """
    combined = []

    # PDF text (if file exists)
    if pdf_path and pdf_path.exists():
        combined.append(_extract_pdf_text_first_pages(pdf_path, max_pages=2))

    # Fallback: parsed page text
    for i in (1, 2):
        ptxt = pages_dir / f"page_{i}.txt"
        if ptxt.exists():
            try:
                combined.append(ptxt.read_text(encoding="utf-8"))
            except Exception:
                pass

    blob = "\n".join([t for t in combined if t]).strip()

    company = None
    fiscal_year_date = None
    fiscal_year = None

    if blob:
        mco = _RX_COMPANY.search(blob)
        if mco:
            company = mco.group(1).strip()

        mfy = _RX_FY_DATE.search(blob)
        if mfy:
            fiscal_year_date = mfy.group(1).strip()
            my = re.search(r"(?:19|20)\d{2}", fiscal_year_date)
            if my:
                fiscal_year = my.group(0)

    # As a last resort, try year from doc_id (e.g., Apple_SEA_2024)
    if not fiscal_year:
        m = re.search(r"(?:19|20)\d{2}", doc_id or "")
        if m:
            fiscal_year = m.group(0)

    doc_name = pdf_path.name if (pdf_path and pdf_path.exists()) else None
    return company, fiscal_year_date, fiscal_year, doc_name


def unify_bbox(block: dict):
    """Prefer absolute bbox; else normalized; else None. Expect [x0, y0, x1, y1]."""
    b_abs = block.get("bbox_abs")
    if isinstance(b_abs, (list, tuple)) and len(b_abs) == 4:
        return b_abs
    b_norm = block.get("bbox_norm")
    if isinstance(b_norm, (list, tuple)) and len(b_norm) == 4:
        return b_norm
    return None

def block_text_guess(b: dict):
    """Lightweight text capture when the layout JSON already carries text."""
    for k in ("text", "content", "value"):
        v = b.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None

# ----------------------------
# Your original helper functions
# ----------------------------
def list_tables(doc_dir: Path, page: int):
    out = []
    tdir = doc_dir / "tables"
    if not tdir.exists():
        return out
    # our table naming: table_p{page}_{idx}.csv
    for p in sorted(tdir.glob(f"table_p{page}_*.csv")):
        out.append(str(p))
    # also include camelot-style files if they exist
    for p in sorted(tdir.glob("table_lattice_*.csv")):
        out.append(str(p))
    for p in sorted(tdir.glob("table_stream_*.csv")):
        out.append(str(p))
    return out

def list_figures(doc_dir: Path, page: int):
    out = []
    pdir = doc_dir / "figures" / f"page_{page}"
    if not pdir.exists():
        return out
    for p in sorted(pdir.glob("figure_*.png")):
        out.append(str(p))
    return out

def load_ocr_pages(doc_dir: Path):
    csvp = doc_dir / "ocr_pages.csv"
    if not csvp.exists():
        return set()
    try:
        df = pd.read_csv(csvp)
        return set(int(x) for x in df["page"].tolist())
    except Exception:
        return set()

def detect_docling_outputs(doc_dir: Path):
    d = doc_dir / "docling"
    if not d.exists():
        return None, None
    stem = doc_dir.name
    md = d / f"{stem}.md"
    js = d / f"{stem}.json"
    return (str(md) if md.exists() else None, str(js) if js.exists() else None)

def detect_tables_backend(doc_dir: Path, page: int):
    """Infer how tables were extracted by file naming."""
    tdir = doc_dir / "tables"
    if not tdir.exists():
        return None
    # pdfplumber fallback uses page-specific names:
    plumber = list(tdir.glob(f"table_p{page}_*.csv"))
    # camelot variants:
    lattice = list(tdir.glob("table_lattice_*.csv"))
    stream  = list(tdir.glob("table_stream_*.csv"))
    if plumber:
        return "pdfplumber"
    if lattice:
        return "camelot:lattice"
    if stream:
        return "camelot:stream"
    return "unknown"

# ----------------------------
# Main builder (enriched)
# ----------------------------
def build_for_document(doc_dir: Path):
    doc_id = doc_dir.name

    layout_dir = doc_dir / "layout"
    pages_dir  = doc_dir / "pages"
    words_jsonl = doc_dir / f"{doc_id}_words.jsonl"
    ocr_pages = load_ocr_pages(doc_dir)
    docling_md, docling_json = detect_docling_outputs(doc_dir)

    # Pick the source PDF from data/upload
    source_pdf = (UPLOAD_ROOT / f"{doc_id}.pdf")
    if not source_pdf.exists():
        # allow a generic Apple_SEA.pdf fallback if your parsed dir name differs slightly
        fallback = UPLOAD_ROOT / "Apple_SEA.pdf"
        if fallback.exists():
            source_pdf = fallback

    # NEW: robust extraction (PDF ➜ fall back to parsed page text)
    company, fiscal_year_date, fiscal_year, doc_name = extract_company_fy(source_pdf, pages_dir, doc_id)

    # Fallback fiscal year from doc_id if PDF parse failed
    if not fiscal_year:
        m = re.search(r"(?:19|20)\d{2}", doc_id)
        if m:
            fiscal_year = m.group(0)

    layout_dir = doc_dir / "layout"
    pages_dir  = doc_dir / "pages"
    words_jsonl = doc_dir / f"{doc_id}_words.jsonl"
    ocr_pages = load_ocr_pages(doc_dir)
    docling_md, docling_json = detect_docling_outputs(doc_dir)

    # Outputs
    STAGED_ROOT.mkdir(parents=True, exist_ok=True)
    out_jsonl = STAGED_ROOT / f"{doc_id}.jsonl"
    out_md    = STAGED_ROOT / f"{doc_id}.md"

    # Gather page JSONs
    page_jsons = sorted(layout_dir.glob("page_*.json"))
    if not page_jsons:
        print(f"[skip] No layout for {doc_id} in {layout_dir}")
        return

    # Write JSONL
    with open(out_jsonl, "w", encoding="utf-8") as jf:
        # Track a rolling 'section' per page (last Title seen on that page)
        page_to_section = {}

        for pj in page_jsons:
            page = int(pj.stem.split("_")[1])
            layout = json.loads(pj.read_text(encoding="utf-8"))
            blocks = layout.get("blocks", [])
            layout_backend = layout.get("backend") or "unknown"

            # choose backend strings for this page
            text_backend = "ocr+tesseract" if page in ocr_pages else "pdfplumber"
            tables_backend = detect_tables_backend(doc_dir, page)

            current_section = page_to_section.get(page)

            for bi, b in enumerate(blocks, start=1):
                btype = b.get("type", "Unknown")

                # Update rolling section on Title
                if btype == "Title":
                    t = block_text_guess(b)
                    current_section = (t or f"Title p{page}").strip()
                    page_to_section[page] = current_section

                rec = {
                    "doc_id": doc_id,

                    # NEW: PDF-derived enrichments
                    "doc_name": doc_name,                 # e.g., Apple_SEA.pdf
                    "company": company,                   # e.g., Apple Inc.
                    "fiscal_year_date": fiscal_year_date, # e.g., September 28, 2024
                    "fiscal_year": fiscal_year,           # e.g., 2024

                    "page": page,
                    "section": current_section,           # may be None
                    "block_id": f"p{page}_b{bi}",
                    "block_type": btype,

                    # NEW: unified bbox + keep originals
                    "bbox": unify_bbox(b),
                    "bbox_norm": b.get("bbox_norm"),
                    "bbox_abs":  b.get("bbox_abs"),

                    # NEW: textual content if present in layout
                    "text": block_text_guess(b) if btype in {"Text","Title","List"} else None,

                    "sources": {
                        "layout": layout_backend,
                        "text": text_backend if btype in {"Text","Title","List"} else None,
                        "tables": tables_backend if btype == "Table" else None,
                        "figures": "pymupdf+pillow" if btype == "Figure" else None,
                    },

                    # NEW: pointer to original PDF on disk (if exists)
                    "source_path": str(source_pdf) if source_pdf.exists() else None,

                    "provenance": {
                        "layout_json": str(pj),
                        "page_text":   str(pages_dir / f"page_{page}.txt"),
                        "words_jsonl": str(words_jsonl) if words_jsonl.exists() else None,
                        "ocr_log":     str(doc_dir / "ocr_pages.csv") if (doc_dir / "ocr_pages.csv").exists() else None,
                        "table_csvs":  list_tables(doc_dir, page) if btype == "Table" else [],
                        "figure_pngs": list_figures(doc_dir, page) if btype == "Figure" else [],
                        "docling_md":  docling_md,
                        "docling_json": docling_json,
                    },
                    "ocr_used_on_page": (page in ocr_pages),
                    "notes": ""
                }
                jf.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write Markdown summary with links
    lines = []
    # Header: doc_id — file name — FY <year> — Staged Metadata (Lab 5)
    title_bits = [doc_id]
    if doc_name:
        title_bits.append(doc_name)
    if fiscal_year:
        title_bits.append(f"FY {fiscal_year}")
    lines.append("# " + " — ".join(title_bits) + " — Staged Metadata (Lab 5)\n")
    if company:
        lines.append(f"- Company: **{company}**")
    if fiscal_year_date:
        lines.append(f"- Fiscal year end: **{fiscal_year_date}**")
    lines.append(f"- Source parsed dir: `{doc_dir}`")
    lines.append(f"- JSONL: `{STAGED_ROOT / f'{doc_id}.jsonl'}`")
    lines.append(f"- Words (if present): `{words_jsonl if words_jsonl.exists() else '—'}`")
    lines.append(f"- Docling: md=`{docling_md}` json=`{docling_json}`")
    lines.append(f"- Source PDF: `{source_pdf if source_pdf.exists() else '—'}`\n")
    for pj in page_jsons:
        page = int(pj.stem.split("_")[1])
        page_txt = pages_dir / f"page_{page}.txt"
        tables = list_tables(doc_dir, page)
        figs   = list_figures(doc_dir, page)
        ocr_tag = " (OCR used)" if page in ocr_pages else ""
        lines.append(f"## Page {page}{ocr_tag}")
        lines.append(f"- Layout JSON: `{pj}`")
        lines.append(f"- Page text: `{page_txt}`")
        if tables:
            lines.append(f"- Tables ({len(tables)}):")
            for t in tables:
                lines.append(f"  - `{t}`")
        if figs:
            lines.append(f"- Figures ({len(figs)}):")
            for im in figs:
                lines.append(f"  - `{im}`")
        lines.append("")  # blank line

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Staged: {out_jsonl} and {out_md}")

# ----------------------------
# CLI entrypoint (unchanged)
# ----------------------------
def main():
    docs = [p for p in PARSED_ROOT.iterdir() if p.is_dir()]
    if not docs:
        print("No parsed docs found under data/parsed/. Run Labs 1–3 first.")
        return
    for d in sorted(docs):
        build_for_document(d)

if __name__ == "__main__":
    main()
