#!/usr/bin/env python
"""
Lab 4 — Docling (UNIFIED pipeline):
- Input:  data/upload/*.pdf
- Output: data/parsed/docling/md/<stem>.md      (reading-order Markdown)
         data/parsed/docling/json/<stem>.json  (full DoclingDocument)
         data/parsed/docling/summary.csv       (small per-file summary)

Dependencies:
  pip install docling pandas
"""
import os
from pathlib import Path

# Use a local cache folder inside the project
os.environ["HF_HOME"] = str(Path(".hf_cache").resolve())

# Force the hub to avoid symlinks & hardlinks
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_ENABLE_HARDLINKS"] = "0"

# (Optional) silence the warning message about symlinks
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# FIXED: Monkeypatch to handle the argument that's being passed
try:
    import huggingface_hub.file_download as _fd
    # These functions are being called with a path argument, so accept it but ignore it
    _fd.are_symlinks_supported = lambda path=None: False
    _fd.are_hardlinks_supported = lambda path=None: False
except Exception:
    pass

# Alternative more robust monkeypatch if the above doesn't work
try:
    import huggingface_hub
    import huggingface_hub.file_download
    
    # Create wrapper functions that can handle any number of arguments
    def no_symlinks(*args, **kwargs):
        return False
    
    def no_hardlinks(*args, **kwargs):
        return False
    
    # Apply the patches
    huggingface_hub.file_download.are_symlinks_supported = no_symlinks
    huggingface_hub.file_download.are_hardlinks_supported = no_hardlinks
    
    # Also patch at module level if it exists there
    if hasattr(huggingface_hub, 'are_symlinks_supported'):
        huggingface_hub.are_symlinks_supported = no_symlinks
    if hasattr(huggingface_hub, 'are_hardlinks_supported'):
        huggingface_hub.are_hardlinks_supported = no_hardlinks
        
except Exception as e:
    print(f"Warning: Could not patch huggingface_hub symlink functions: {e}")

import json
import pandas as pd
from rich import print

# --- Docling core ---
from docling.document_converter import DocumentConverter
# DoclingDocument is the unified representation containing:
#  - text blocks in reading order
#  - tables (structured rows/cols)
#  - figures/images
#  - layout metadata (bboxes, pages, etc.)

# --- IO paths ---
IN_DIR   = Path("data/upload")
OUT_MD   = Path("data/parsed/docling/md")
OUT_JSON = Path("data/parsed/docling/json")
OUT_SUM  = Path("data/parsed/docling/summary.csv")

def convert_one(pdf_path: Path):
    """Run Docling on a single PDF and return (markdown_text, json_obj)."""
    # Check if GPU is available and print status
    import torch
    if torch.cuda.is_available():
        print(f"  → Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("  → Using CPU (GPU not detected)")
    
    conv = DocumentConverter()               # uses default models/pipeline
    res  = conv.convert(str(pdf_path))       # parse → DocumentConversionResult
    doc  = res.document                      # the unified DoclingDocument
    md   = doc.export_to_markdown()          # reading-order text (tables inline)
    
    # Fixed: Pydantic v2 doesn't have ensure_ascii parameter
    # Try the newer method first, fall back to older method
    try:
        # For newer Pydantic versions
        js   = json.loads(doc.model_dump_json(indent=2))
    except TypeError:
        # For older versions that might need different approach
        js   = doc.model_dump()
    
    return md, js

def summarize(doc_json: dict):
    """Light summary to compare files (counts only)."""
    pages   = doc_json.get("page_count") or len(doc_json.get("pages", []) or [])
    tables  = len(doc_json.get("tables", []) or [])
    figures = len(doc_json.get("pictures", []) or [])
    blocks  = len(doc_json.get("elements", []) or [])  # may vary by version
    return dict(pages=pages, tables=tables, figures=figures, blocks=blocks)

if __name__ == "__main__":
    # Create output folders once
    OUT_MD.mkdir(parents=True, exist_ok=True)
    OUT_JSON.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(IN_DIR.rglob("*.pdf"))
    if not pdfs:
        print("[yellow]No PDFs found in data/upload/ — add files and rerun.[/]")
        raise SystemExit

    print(f"[cyan]Docling (unified) — processing {len(pdfs)} PDF(s)[/]")
    rows = []
    for i, pdf in enumerate(pdfs, start=1):
        stem = pdf.stem
        print(f"  [{i}/{len(pdfs)}] {pdf.name}")

        # 1) Convert to unified DoclingDocument
        md_text, doc_json = convert_one(pdf)

        # 2) Save unified exports
        (OUT_MD / f"{stem}.md").write_text(md_text, encoding="utf-8")
        
        # Handle both dict and object for doc_json
        if isinstance(doc_json, dict):
            json_str = json.dumps(doc_json, ensure_ascii=False, indent=2)
        else:
            # If it's still a Pydantic model, convert it
            json_str = json.dumps(doc_json.model_dump() if hasattr(doc_json, 'model_dump') else doc_json, 
                                 ensure_ascii=False, indent=2)
        
        (OUT_JSON / f"{stem}.json").write_text(json_str, encoding="utf-8")

        # 3) Append a small summary row
        s = summarize(doc_json)
        s["file"] = pdf.name
        rows.append(s)

    # 4) Write/append summary CSV
    df = pd.DataFrame(rows, columns=["file","pages","tables","figures","blocks"])
    df.to_csv(OUT_SUM, index=False)
    print(f"\n[bold green]Done.[/]")
    print(f"  Markdown → {OUT_MD}")
    print(f"  JSON     → {OUT_JSON}")
    print(f"  Summary  → {OUT_SUM}")