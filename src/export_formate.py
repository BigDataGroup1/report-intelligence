from pathlib import Path
import json
import pandas as pd

PARSED_ROOT = Path("data/parsed")
STAGED_ROOT = Path("data/staged")
OUT_ROOT = Path("data/formats")

import re

PARSED_ROOT = Path("data/parsed")  # keep your existing constant

def _norm_path(pstr: str) -> Path:
    """Convert Windows-style 'a\\b\\c.csv' into POSIX-ish Path and return Path."""
    return Path(str(pstr).replace("\\", "/"))

def _fallback_table_csv(doc_id: str, page: int) -> Path | None:
    """
    If provenance points to a missing CSV, try to find a table CSV for this page.
    Looks for patterns like: table_p{page}_*.csv or general CSVs if page-less.
    """
    tdir = PARSED_ROOT / doc_id / "tables"
    if not tdir.exists():
        return None
    # 1) Try explicit per-page pattern
    candidates = sorted(tdir.glob(f"table_p{page}_*.csv"))
    if candidates:
        return candidates[0]
    # 2) Try camelot outputs without page in filename (lattice/stream)
    candidates = sorted(tdir.glob("table_lattice_*.csv")) + sorted(tdir.glob("table_stream_*.csv"))
    if candidates:
        return candidates[0]
    # 3) Last resort: any CSV in tables dir
    candidates = sorted(tdir.glob("*.csv"))
    return candidates[0] if candidates else None

# -------- helpers --------
def load_words_by_page(doc_id: str):
    words_jl = PARSED_ROOT / doc_id / f"{doc_id}_words.jsonl"
    pages = {}
    if not words_jl.exists():
        return pages
    with open(words_jl, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            p = int(rec.get("page", -1))
            if p < 0: 
                continue
            pages.setdefault(p, []).append(rec)
    # sort each page roughly top-to-bottom, left-to-right
    for p, arr in pages.items():
        arr.sort(key=lambda r: (r.get("bbox_norm", {}).get("y0", 0.0), r.get("bbox_norm", {}).get("x0", 0.0)))
    return pages

def words_in_block(words_page, bbox):
    """Return words whose bbox center falls inside block bbox_norm."""
    if not words_page or not bbox:
        return []
    x0,y0,x1,y1 = bbox.get("x0",0), bbox.get("y0",0), bbox.get("x1",1), bbox.get("y1",1)
    out = []
    for w in words_page:
        bb = w.get("bbox_norm") or {}
        cx = (bb.get("x0",0)+bb.get("x1",0))/2
        cy = (bb.get("y0",0)+bb.get("y1",0))/2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(w)
    # already mostly sorted by y0,x0; keep that order
    return out

def words_to_text(words):
    # simple join with spaces; collapse multiple spaces later in renderers if needed
    return " ".join((w.get("word") or "").strip() for w in words if (w.get("word") or "").strip())

def csv_to_markdown_table(csv_path: Path, max_cols=30, max_rows=50):
    try:
        df = pd.read_csv(csv_path, header=0)
    except Exception:
        try:
            df = pd.read_csv(csv_path, header=None)
        except Exception:
            return f"\n> [table: could not read `{csv_path}`]\n"
    if df.shape[1] > max_cols:
        df = df.iloc[:, :max_cols]
    if df.shape[0] > max_rows:
        df = df.iloc[:max_rows, :]
    # convert to MD pipe table
    cols = [str(c) if c is not None else "" for c in (df.columns.tolist())]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"]*len(cols)) + " |"
    body_lines = []
    for _, row in df.iterrows():
        body_lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row.tolist()) + " |")
    return "\n".join([header, sep] + body_lines) + "\n"

def doc_ids_to_export():
    # export only docs that have staged jsonl
    return sorted(p.stem for p in STAGED_ROOT.glob("*.jsonl"))

# -------- core exporters --------
def export_markdown_for_doc(doc_id: str):
    words_by_page = load_words_by_page(doc_id)
    in_jsonl = STAGED_ROOT / f"{doc_id}.jsonl"
    out_dir = OUT_ROOT / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"{doc_id}.md"

    lines = []
    lines.append(f"# {doc_id}\n")

    # group staged records by page, preserve order
    by_page = {}
    with open(in_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            by_page.setdefault(rec["page"], []).append(rec)

    for page in sorted(by_page.keys()):
        lines.append(f"\n## Page {page}\n")
        for rec in by_page[page]:
            btype = rec.get("block_type","Unknown")
            bbox  = rec.get("bbox_norm")
            prov  = rec.get("provenance", {})
            # reconstruct text from words within bbox (for text-like blocks)
            text = ""
            if btype in {"Text","Title","List"} and bbox:
                words_page = words_by_page.get(page, [])
                text = words_to_text(words_in_block(words_page, bbox))

            if btype == "Title":
                lines.append(f"\n### {text}\n" if text else "\n### (Title)\n")
            elif btype == "List":
                # naive: split by "•" or periods; if none, write as a single bullet
                items = [t.strip() for t in text.split("•") if t.strip()] or ([text] if text else [])
                for it in items:
                    lines.append(f"- {it}")
                if items:
                    lines.append("")
            elif btype == "Text":
                if text:
                    lines.append(text + "\n")
            elif btype == "Table":
                table_csvs = prov.get("table_csvs", []) or []
                if table_csvs:
                    # pick the first CSV for this block (often 1:1)
                    lines.append(csv_to_markdown_table(Path(table_csvs[0])))
                else:
                    lines.append("> [table placeholder — no CSV found]\n")
            elif btype == "Figure":
                figs = prov.get("figure_pngs", []) or []
                if figs:
                    # embed first figure
                    rel = figs[0]
                    lines.append(f"![figure]({rel})\n")
                else:
                    lines.append("> [figure placeholder — no PNG found]\n")
            else:
                # Unknown/Other
                if text:
                    lines.append(text + "\n")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Markdown → {out_md}")

def export_json_for_doc(doc_id: str):
    words_by_page = load_words_by_page(doc_id)
    in_jsonl = STAGED_ROOT / f"{doc_id}.jsonl"
    out_dir = OUT_ROOT / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{doc_id}.json"

    out = []
    with open(in_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            page = rec["page"]
            btype = rec.get("block_type","Unknown")
            bbox  = rec.get("bbox_norm")
            prov  = rec.get("provenance", {})

            block = {
                "doc_id": rec["doc_id"],
                "page": page,
                "type": btype,
                "bbox_norm": bbox,
                "sources": rec.get("sources"),
                "ocr_used_on_page": rec.get("ocr_used_on_page", False),
                "provenance": prov
            }

            # Attach content depending on type
            if btype in {"Text","Title","List"} and bbox:
                words_page = words_by_page.get(page, [])
                txt = words_to_text(words_in_block(words_page, bbox))
                block["text"] = txt

            if btype == "Table":
                table_csvs = prov.get("table_csvs", []) or []
                csv_path = None
                for c in table_csvs:
                    p = _norm_path(c)
                    if p.exists():
                        csv_path = p
                        break
                if csv_path is None:
                    csv_path = _fallback_table_csv(doc_id, page)

                if csv_path and csv_path.exists():
                    try:
                        df = pd.read_csv(csv_path, header=0)
                    except Exception:
                        df = pd.read_csv(csv_path, header=None)
                    block["table"] = {"rows": df.fillna("").astype(str).values.tolist(),
                                        "source_csv": str(csv_path)}
                else:
                    block["table"] = {"rows": [], "source_csv": None, "note": f"missing CSV for page {page}"}


            if btype == "Figure":
                figs = prov.get("figure_pngs", []) or []
                block["figure"] = {"paths": figs}

            out.append(block)

    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ JSON → {out_json}")

def export_text_for_doc(doc_id: str):
    """Plain text baseline: just concatenate block texts and render tables as TSV-ish."""
    words_by_page = load_words_by_page(doc_id)
    in_jsonl = STAGED_ROOT / f"{doc_id}.jsonl"
    out_dir = OUT_ROOT / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / f"{doc_id}.txt"

    lines = []
    with open(in_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            page = rec["page"]
            btype = rec.get("block_type","Unknown")
            bbox  = rec.get("bbox_norm")
            prov  = rec.get("provenance", {})

            if btype in {"Title","Text","List"} and bbox:
                words_page = words_by_page.get(page, [])
                txt = words_to_text(words_in_block(words_page, bbox))
                if txt:
                    lines.append(txt)

            if btype == "Table":
                table_csvs = prov.get("table_csvs", []) or []
                csv_path = None
                for c in table_csvs:
                    p = _norm_path(c)
                    if p.exists():
                        csv_path = p
                        break
                if csv_path is None:
                    csv_path = _fallback_table_csv(doc_id, page)

                if csv_path and csv_path.exists():
                    try:
                        df = pd.read_csv(csv_path, header=0)
                    except Exception:
                        df = pd.read_csv(csv_path, header=None)
                    for _, row in df.iterrows():
                        lines.append("\t".join("" if pd.isna(v) else str(v) for v in row.tolist()))
                else:
                    lines.append(f"[TABLE missing for page {page}]")


            if btype == "Figure":
                lines.append("[FIGURE]")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ TXT → {out_txt}")

def export_one(doc_id: str):
    staged = STAGED_ROOT / f"{doc_id}.jsonl"
    if not staged.exists():
        print(f"[skip] missing staged: {staged}")
        return
    (OUT_ROOT / doc_id).mkdir(parents=True, exist_ok=True)
    export_markdown_for_doc(doc_id)
    export_json_for_doc(doc_id)
    export_text_for_doc(doc_id)

def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ids = doc_ids_to_export()
    if not ids:
        print("No staged docs found in data/staged/*.jsonl")
        return
    for doc_id in ids:
        print(f"\n== Exporting {doc_id} ==")
        export_one(doc_id)

if __name__ == "__main__":
    main()
