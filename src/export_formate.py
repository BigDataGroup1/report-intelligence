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

# ===================== NEW: Retrieval Comparison Logic =====================

def _estimate_full_text_len(words_by_page: dict[int, list[dict]]) -> int:
    """Approximate total source text length from OCR words."""
    total_words = sum(len(v) for v in words_by_page.values())
    # average word length ~5 incl. spaces; conservative multiplier
    return total_words * 6

def _count_tables_and_cells_from_staged(doc_id: str) -> tuple[int, int]:
    """From staged JSONL and available CSVs, estimate table count and total cells."""
    in_jsonl = STAGED_ROOT / f"{doc_id}.jsonl"
    tcount, cells = 0, 0
    if not in_jsonl.exists():
        return 0, 0
    with open(in_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("block_type") != "Table":
                continue
            tcount += 1
            prov = rec.get("provenance", {}) or {}
            page = rec.get("page")
            csv_path = None
            for c in prov.get("table_csvs", []) or []:
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
                r, c = df.shape
                cells += int(r) * int(c)
    return tcount, cells

def _load_export_paths(doc_id: str) -> dict:
    out_dir = OUT_ROOT / doc_id
    return {
        "md": out_dir / f"{doc_id}.md",
        "json": out_dir / f"{doc_id}.json",
        "txt": out_dir / f"{doc_id}.txt",
    }

def _format_metrics(doc_id: str) -> dict:
    """Compute comparable retrieval metrics for md/json/txt outputs."""
    words_by_page = load_words_by_page(doc_id)
    full_len_est = _estimate_full_text_len(words_by_page)
    tcount, cells_est = _count_tables_and_cells_from_staged(doc_id)
    paths = _load_export_paths(doc_id)

    metrics = {}
    # Markdown
    md_len = (paths["md"].read_text(encoding="utf-8") if paths["md"].exists() else "")
    md_headings = len(re.findall(r"^#{1,6}\s", md_len, flags=re.MULTILINE))
    md_tables = len(re.findall(r"^\|\s.*\s\|$", md_len, flags=re.MULTILINE))
    md_figs = len(re.findall(r"!\[", md_len))
    metrics["markdown"] = {
        "bytes": len(md_len.encode("utf-8")) if md_len else 0,
        "text_coverage_ratio": (len(md_len) / max(1, full_len_est)) if md_len else 0.0,
        "structure_signals": md_headings + md_tables,  # chunking cues
        "tables_cells_est": cells_est,  # we render tables; use staged-derived cells
        "fig_refs": md_figs,
    }

    # JSON
    jdata = []
    if paths["json"].exists():
        try:
            jdata = json.loads(paths["json"].read_text(encoding="utf-8"))
        except Exception:
            jdata = []
    json_text_len = 0
    json_titles = json_texts = json_lists = 0
    json_tables_cells = 0
    json_figs = 0
    for b in jdata:
        if "text" in b and isinstance(b["text"], str):
            json_text_len += len(b["text"])
        t = (b.get("type") or "").lower()
        if t == "title":
            json_titles += 1
        elif t == "text":
            json_texts += 1
        elif t == "list":
            json_lists += 1
        if "table" in b and isinstance(b["table"], dict):
            rows = b["table"].get("rows") or []
            # rows is list[list]; count cells
            if rows and isinstance(rows, list) and isinstance(rows[0], list):
                r = len(rows)
                c = max((len(rw) for rw in rows), default=0)
                json_tables_cells += r * c
        if "figure" in b:
            paths_ = (b["figure"] or {}).get("paths") or []
            json_figs += 1 if paths_ else 0
    metrics["json"] = {
        "bytes": len((paths["json"].read_text(encoding="utf-8") if paths["json"].exists() else "").encode("utf-8")),
        "text_coverage_ratio": (json_text_len / max(1, full_len_est)),
        "structure_signals": json_titles + json_texts + json_lists,  # typed blocks usable as metadata
        "tables_cells_est": max(json_tables_cells, cells_est),  # prefer explicit count
        "fig_refs": json_figs,
    }

    # TXT
    txt = (paths["txt"].read_text(encoding="utf-8") if paths["txt"].exists() else "")
    # tables rendered as TSV lines (count with tabs)
    tsv_lines = [ln for ln in txt.splitlines() if "\t" in ln and not ln.strip().startswith("[TABLE")]
    # approximate cells: sum columns per TSV line
    txt_cells = 0
    for ln in tsv_lines:
        txt_cells += max(1, ln.count("\t") + 1)

    metrics["txt"] = {
        "bytes": len(txt.encode("utf-8")) if txt else 0,
        "text_coverage_ratio": (len(txt) / max(1, full_len_est)) if txt else 0.0,
        "structure_signals": 0,  # flat text
        "tables_cells_est": txt_cells,
        "fig_refs": 0,  # figures not preserved
    }

    # Also attach staged-level “potential” to understand context
    metrics["_potential"] = {
        "full_text_len_est": full_len_est,
        "tables_in_staged": tcount,
        "cells_in_staged_est": cells_est,
    }
    return metrics

def _score_formats(metrics: dict, use_case: str = "semantic_search") -> dict:
    """
    Score each format with simple weighted heuristics depending on downstream retrieval:
      - semantic_search: emphasize text coverage + structure cues
      - keyword_search: emphasize bytes (indexable size) + structure
      - table_qa: emphasize table cells preserved + text coverage
    Returns dict with per-format scores and winner.
    """
    weights = {
        "semantic_search": {"text": 0.5, "struct": 0.3, "tables": 0.15, "figs": 0.05},
        "keyword_search":  {"text": 0.35, "struct": 0.35, "tables": 0.15, "figs": 0.15},
        "table_qa":        {"text": 0.25, "struct": 0.15, "tables": 0.55, "figs": 0.05},
    }.get(use_case, {"text": 0.5, "struct": 0.3, "tables": 0.15, "figs": 0.05})

    # normalizers to keep 0..1-ish ranges
    # structure: use max across formats for relative scaling
    struct_max = max(metrics[f]["structure_signals"] for f in ("markdown", "json", "txt")) or 1
    tables_max = max(metrics[f]["tables_cells_est"] for f in ("markdown", "json", "txt")) or 1
    figs_max = max(metrics[f]["fig_refs"] for f in ("markdown", "json", "txt")) or 1

    scores = {}
    for fmt in ("markdown", "json", "txt"):
        m = metrics[fmt]
        text_cov = min(1.0, m["text_coverage_ratio"])
        struct = m["structure_signals"] / struct_max
        tables = m["tables_cells_est"] / tables_max
        figs = m["fig_refs"] / figs_max
        score = (
            weights["text"] * text_cov +
            weights["struct"] * struct +
            weights["tables"] * tables +
            weights["figs"] * figs
        )
        scores[fmt] = round(float(score), 4)

    # best format name
    winner = max(scores.items(), key=lambda kv: kv[1])[0]
    return {"scores": scores, "winner": winner, "use_case": use_case}

def compare_formats_for_doc(doc_id: str, use_case: str = "semantic_search") -> dict:
    """
    Public API: compute metrics + score + recommendation for one doc.
    """
    metrics = _format_metrics(doc_id)
    verdict = _score_formats(metrics, use_case=use_case)
    return {
        "doc_id": doc_id,
        "use_case": verdict["use_case"],
        "winner": verdict["winner"],
        "scores": verdict["scores"],
        "metrics": {
            "markdown": metrics["markdown"],
            "json": metrics["json"],
            "txt": metrics["txt"],
            "potential": metrics["_potential"],
        },
    }

def compare_all_docs(ids: list[str], use_case: str = "semantic_search") -> pd.DataFrame:
    """
    Run comparison across all docs and persist reports (CSV + JSON).
    """
    results = []
    blob = []
    for doc_id in ids:
        r = compare_formats_for_doc(doc_id, use_case=use_case)
        blob.append(r)
        s = r["scores"]
        pm = r["metrics"]["potential"]
        results.append({
            "doc_id": doc_id,
            "use_case": r["use_case"],
            "winner": r["winner"],
            "score_markdown": s["markdown"],
            "score_json": s["json"],
            "score_txt": s["txt"],
            "text_cov_md": r["metrics"]["markdown"]["text_coverage_ratio"],
            "text_cov_json": r["metrics"]["json"]["text_coverage_ratio"],
            "text_cov_txt": r["metrics"]["txt"]["text_coverage_ratio"],
            "struct_md": r["metrics"]["markdown"]["structure_signals"],
            "struct_json": r["metrics"]["json"]["structure_signals"],
            "struct_txt": r["metrics"]["txt"]["structure_signals"],
            "tables_cells_md": r["metrics"]["markdown"]["tables_cells_est"],
            "tables_cells_json": r["metrics"]["json"]["tables_cells_est"],
            "tables_cells_txt": r["metrics"]["txt"]["tables_cells_est"],
            "tables_in_staged": pm["tables_in_staged"],
            "cells_in_staged_est": pm["cells_in_staged_est"],
        })
    df = pd.DataFrame(results)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "_comparison.csv").write_text(df.to_csv(index=False), encoding="utf-8")
    (OUT_ROOT / "_comparison.json").write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Comparison report → {OUT_ROOT / '_comparison.csv'}")
    print(f"✓ Comparison details → {OUT_ROOT / '_comparison.json'}")
    # Print a small human-readable summary
    if not df.empty:
        summary = df[["doc_id","winner","score_markdown","score_json","score_txt"]]
        print("\n== Retrieval Format Recommendation ==")
        for _, row in summary.iterrows():
            print(f"- {row['doc_id']}: {row['winner']} "
                  f"(md={row['score_markdown']:.3f}, json={row['score_json']:.3f}, txt={row['score_txt']:.3f})")
    return df

# ===================== /NEW =====================

def main(use_case: str = "semantic_search"):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ids = doc_ids_to_export()
    if not ids:
        print("No staged docs found in data/staged/*.jsonl")
        return
    for doc_id in ids:
        print(f"\n== Exporting {doc_id} ==")
        export_one(doc_id)
    # After exporting, compare formats for retrieval and print/store a recommendation
    print(f"\n== Comparing formats for downstream retrieval (use_case='{use_case}') ==")
    compare_all_docs(ids, use_case=use_case)

if __name__ == "__main__":
    # Choose from: "semantic_search", "keyword_search", "table_qa"
    main(use_case="semantic_search")
