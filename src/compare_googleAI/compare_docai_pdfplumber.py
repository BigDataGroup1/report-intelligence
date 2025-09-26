import argparse, json, csv, pathlib, os, difflib
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

# ---------- utilities ----------
def write_text(path: pathlib.Path, text: str):
    # Write text to file, creating directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")

def write_json(path: pathlib.Path, obj: Any):
    # Write object as formatted JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def write_csv(path: pathlib.Path, rows: List[List[str]]):
    # Write 2D list as CSV file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

def table_shape(rows: List[List[str]]) -> Tuple[int, int]:
    # Return table dimensions (rows, cols)
    return len(rows), max((len(r) for r in rows), default=0)

# ---------- pdfplumber JSONL -> simple text ----------
def load_jsonl(jsonl_path: str) -> List[Dict[str, Any]]:
    # Load JSONL file where each line is a JSON object
    items = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items

def jsonl_to_text(items: List[Dict[str, Any]]) -> str:
    # Convert pdfplumber JSONL tokens to readable text with page breaks
    text_lines, last_page = [], None
    # Collect words and track page changes
    for it in items:
        p = it.get("page")
        w = (it.get("word") or "").strip()
        if p != last_page:
            if last_page is not None:
                text_lines.append("")  # page break marker
            last_page = p
        if w:
            text_lines.append(w)
    # Join words into lines, preserve page breaks
    out, line = [], []
    for token in text_lines:
        if token == "":
            if line:
                out.append(" ".join(line)); line = []
            out.append("")  # keep page break
        else:
            line.append(token)
    if line:
        out.append(" ".join(line))
    return "\n".join(out).strip()

def load_csv_rows(path: Optional[str]) -> List[List[str]]:
    # Load CSV file as 2D list, return empty if not found
    if not path or not pathlib.Path(path).exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.reader(f))

# ---------- Google Document AI ----------
def run_docai(pdf_path: str, project_id: str, location: str, processor_id: str):
    # Process PDF using Google Document AI
    from google.cloud import documentai as docai
    client = docai.DocumentProcessorServiceClient()
    name = client.processor_path(project_id, location, processor_id)
    with open(pdf_path, "rb") as f:
        raw = docai.RawDocument(content=f.read(), mime_type="application/pdf")
    result = client.process_document(request={"name": name, "raw_document": raw})
    return result.document  # protobuf

def docai_extract(doc):
    # Extract text and tables from Document AI response
    doc_dict = MessageToDict(doc._pb, preserving_proto_field_name=True)
    text = doc.text or ""
    tables = []
    for p in doc.pages:
        for t in getattr(p, "tables", []):
            tables.append(MessageToDict(t._pb, preserving_proto_field_name=True))
    return text, doc_dict, tables

def _get(d: dict, *names):
    # Helper to read either snake_case or camelCase keys
    for n in names:
        if n in d:
            return d[n]
    return None

def docai_table_to_rows(doc_dict: Dict[str, Any], table_dict: Dict[str, Any]) -> List[List[str]]:
    # Convert Document AI table structure to 2D list
    text = _get(doc_dict, "text") or ""
    out: List[List[str]] = []

    def cell_text(cell: Dict[str, Any]) -> str:
        # Extract text from a table cell using text anchors
        s = ""
        layout = _get(cell, "layout") or {}
        ta = _get(layout, "textAnchor", "text_anchor") or {}
        segments = _get(ta, "textSegments", "text_segments") or []
        for seg in segments:
            start = int(_get(seg, "startIndex", "start_index") or 0)
            end   = int(_get(seg, "endIndex", "end_index") or 0)
            s += text[start:end]
        return " ".join(s.split())

    # Process header rows
    for r in (_get(table_dict, "headerRows", "header_rows") or []):
        out.append([cell_text(c) for c in (_get(r, "cells") or [])])
    # Process body rows
    for r in (_get(table_dict, "bodyRows", "body_rows") or []):
        out.append([cell_text(c) for c in (_get(r, "cells") or [])])
    return out

# ---------- comparison metrics ----------
def similarity(a: str, b: str) -> float:
    # Calculate text similarity ratio (0-1)
    return difflib.SequenceMatcher(None, a, b).ratio()

def sample_cell_diffs(rows_a: List[List[str]], rows_b: List[List[str]], samples: int = 5):
    # Find up to 'samples' cell differences between two tables
    diffs = []
    if not rows_a or not rows_b:
        return diffs
    R = min(len(rows_a), len(rows_b))
    C = min(max(len(r) for r in rows_a), max(len(r) for r in rows_b))
    rmax, cmax = min(R, samples), min(C, samples)
    for i in range(rmax):
        for j in range(cmax):
            ca = rows_a[i][j] if j < len(rows_a[i]) else ""
            cb = rows_b[i][j] if j < len(rows_b[i]) else ""
            if ca != cb:
                diffs.append(((i, j), ca, cb))
    return diffs[:samples]

def count_pages_from_jsonl(items: List[Dict[str, Any]]) -> int:
    # Count unique page numbers in JSONL data
    pages = {int(it.get("page", 0)) for it in items}
    return max(pages) if pages else 0

# ---------- main ----------
def main():
    load_dotenv()  # Load environment variables from .env file

    # Parse command line arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=r"D:\Bigdata_Assig1\report-intelligence\data\upload\apple_sea_tabelandtext.pdf")
    ap.add_argument("--jsonl", default=r"D:\Bigdata_Assig1\report-intelligence\data\parsed\apple_sea_tabelandtext\apple_sea_tabelandtext_words.jsonl")
    ap.add_argument("--pp_table_csv", default=r"D:\Bigdata_Assig1\report-intelligence\data\parsed\apple_sea_tabelandtext\tables\table_p3_1.csv",
                    help="Optional: pdfplumber-exported table CSV for side-by-side")
    ap.add_argument("--outdir", default=r"D:\Bigdata_Assig1\report-intelligence\src\compare_googleAI")
    ap.add_argument("--project_id", default=os.getenv("PROJECT_ID"))
    ap.add_argument("--location", default=os.getenv("LOCATION", "us"))
    ap.add_argument("--processor_id", default=os.getenv("PROCESSOR_ID"))
    args = ap.parse_args()

    # Validate required Google Cloud credentials
    if not args.project_id or not args.processor_id:
        raise SystemExit("Missing PROJECT_ID or PROCESSOR_ID (set in .env or pass as flags).")

    # Setup output directory
    OUT = pathlib.Path(args.outdir)
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) Process pdfplumber data
    print("[pdfplumber] reading JSONL…")
    items = load_jsonl(args.jsonl)
    pp_text = jsonl_to_text(items)
    write_text(OUT / "pdfplumber_text.txt", pp_text)
    print(f"  Written: {OUT / 'pdfplumber_text.txt'}")

    pp_rows = load_csv_rows(args.pp_table_csv)
    if pp_rows:
        write_csv(OUT / "pdfplumber_table_1.csv", pp_rows)
        print(f"  Written: {OUT / 'pdfplumber_table_1.csv'}")

    # 2) Process with Google Document AI
    print("[DocAI] processing PDF…")
    doc = run_docai(args.pdf, args.project_id, args.location, args.processor_id)
    doc_text, doc_json, doc_tables = docai_extract(doc)
    write_text(OUT / "docai_text.txt", doc_text)
    write_json(OUT / "docai.json", doc_json)
    write_json(OUT / "docai_tables.json", doc_tables)
    print(f"  Written: {OUT / 'docai_text.txt'}")
    print(f"  Written: {OUT / 'docai.json'}")
    print(f"  Written: {OUT / 'docai_tables.json'}")

    # Extract first table if found
    ga_rows: List[List[str]] = []
    if doc_tables:
        ga_rows = docai_table_to_rows(doc_json, doc_tables[0])
        write_csv(OUT / "docai_table_1.csv", ga_rows)
        print(f"  Written: {OUT / 'docai_table_1.csv'}")

    # 3) Calculate comparison metrics
    sim = similarity(pp_text, doc_text) if pp_text and doc_text else 0.0

    # Collect notes about findings
    notes = []
    if doc_tables:
        notes.append(f"Doc AI found {len(doc_tables)} table(s).")
        hdr = _get(doc_tables[0], "headerRows", "header_rows") or []
        if len(hdr) > 0:
            notes.append("Doc AI flagged header rows.")
    else:
        notes.append("Doc AI found no tables.")

    # Compare table dimensions and sample differences
    shape_note = ""
    diffs_note = ""
    if ga_rows and pp_rows:
        rg, cg = table_shape(ga_rows)
        rp, cp = table_shape(pp_rows)
        shape_note = f"Table shapes — DocAI: {rg}x{cg}, pdfplumber: {rp}x{cp}"
        diffs = sample_cell_diffs(ga_rows, pp_rows, samples=5)
        if diffs:
            diffs_note = "Sample cell diffs:\n" + "\n".join(
                [f"  ({i},{j}) DocAI='{a}' vs pdfplumber='{b}'" for (i,j), a, b in diffs]
            )

    # Calculate cost estimate if pricing provided
    cost_line = ""
    try:
        rate = float(os.getenv("DOC_AI_PRICE_PER_PAGE") or 0.0)
        if rate > 0:
            pages_docai = len(doc.pages)
            est = pages_docai * rate
            cost_line = f"\nEstimated DocAI cost (@ ${rate:.4f}/page × {pages_docai} pages): ${est:.2f}"
    except Exception:
        pass

    # Generate summary report
    summary = f"""Comparison — pdfplumber JSONL vs Google Document AI
PDF: {args.pdf}
Output directory: {OUT}

Text length (characters):
  pdfplumber(JSONL): {len(pp_text)}
  DocAI(text)      : {len(doc_text)}

Text similarity (pdfplumber vs DocAI): {sim:.3f}

Tables:
  DocAI tables found: {len(doc_tables)}
  pdfplumber table CSV provided: {"YES" if pp_rows else "NO"}

{shape_note}
{diffs_note}

Notes:
- """ + "\n- ".join(notes) + f"""
{cost_line}

All output files saved to: {OUT}
"""

    # Save and display summary
    write_text(OUT / "summary.txt", summary)
    print(f"  Written: {OUT / 'summary.txt'}")
    
    print("\n" + "="*60)
    print(summary)
    print("="*60)
    print(f"\nAll files have been saved to: {OUT}")

if __name__ == "__main__":
    main()