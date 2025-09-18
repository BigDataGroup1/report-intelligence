from pathlib import Path
import json
import pandas as pd

PARSED_ROOT = Path("data/parsed")
STAGED_ROOT = Path("data/staged")  # output of Lab 5

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

def build_for_document(doc_dir: Path):
    doc_id = doc_dir.name
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
        for pj in page_jsons:
            page = int(pj.stem.split("_")[1])
            layout = json.loads(pj.read_text(encoding="utf-8"))
            blocks = layout.get("blocks", [])
            layout_backend = layout.get("backend") or "unknown"

            # choose backend strings for this page
            text_backend = "ocr+tesseract" if page in ocr_pages else "pdfplumber"
            tables_backend = detect_tables_backend(doc_dir, page)

            for bi, b in enumerate(blocks, start=1):
                btype = b.get("type", "Unknown")
                rec = {
                    "doc_id": doc_id,
                    "page": page,
                    "block_id": f"p{page}_b{bi}",
                    "block_type": btype,
                    "bbox_norm": b.get("bbox_norm"),
                    "bbox_abs":  b.get("bbox_abs"),
                    "sources": {
                        "layout": layout_backend,
                        "text": text_backend if btype in {"Text","Title","List"} else None,
                        "tables": tables_backend if btype == "Table" else None,
                        "figures": "pymupdf+pillow" if btype == "Figure" else None,
                    },
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
    lines.append(f"# {doc_id} — Staged Metadata (Lab 5)\n")
    lines.append(f"- Source parsed dir: `{doc_dir}`")
    lines.append(f"- JSONL: `{out_jsonl}`")
    lines.append(f"- Words (if present): `{words_jsonl if words_jsonl.exists() else '—'}`")
    lines.append(f"- Docling: md=`{docling_md}` json=`{docling_json}`\n")

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

def main():
    docs = [p for p in PARSED_ROOT.iterdir() if p.is_dir()]
    if not docs:
        print("No parsed docs found under data/parsed/. Run Labs 1–3 first.")
        return
    for d in sorted(docs):
        build_for_document(d)

if __name__ == "__main__":
    main()