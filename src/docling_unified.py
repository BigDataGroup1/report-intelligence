#!/usr/bin/env python
"""
Lab 4 — Docling (UNIFIED pipeline) - Native Features Version
Uses Docling's built-in capabilities for extracting tables, figures, and images.
No external image libraries needed!

- Input:  data/upload/*.pdf
- Output: data/parsed/docling/md/<stem>.md           (reading-order Markdown)
         data/parsed/docling/json/<stem>.json       (full DoclingDocument)
         data/parsed/docling/tables/<stem>/         (individual table files as CSV/HTML)
         data/parsed/docling/figures/<stem>/        (extracted figure images)
         data/parsed/docling/pages/<stem>/          (page images for visualization)
         data/parsed/docling/layout/<stem>/         (layout info with bounding boxes)
         data/parsed/docling/summary.csv            (per-file summary)

Dependencies:
  pip install docling pandas tabulate
"""
import os
from pathlib import Path
import logging
import time

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

# --- Docling core imports ---
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import ImageRefMode, PictureItem, TableItem

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
_log = logging.getLogger(__name__)

# --- IO paths ---
IN_DIR   = Path("data/upload")
OUT_MD   = Path("data/parsed/docling/md")
OUT_JSON = Path("data/parsed/docling/json")
OUT_TAB  = Path("data/parsed/docling/tables")
OUT_FIG  = Path("data/parsed/docling/figures")
OUT_PAGE = Path("data/parsed/docling/pages")
OUT_LAYOUT = Path("data/parsed/docling/layout")  # NEW: Layout output directory
OUT_SUM  = Path("data/parsed/docling/summary.csv")

# Image quality settings
IMAGE_RESOLUTION_SCALE = 2.0  # Higher = better quality (2.0 = ~144 DPI)

def convert_and_extract(pdf_path: Path):
    """
    Run Docling on a single PDF with image extraction enabled.
    Returns the conversion result for further processing.
    """
    # Check if GPU is available and print status
    import torch
    if torch.cuda.is_available():
        print(f"  → Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("  → Using CPU (GPU not detected)")
    
    # Configure pipeline to generate images
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = IMAGE_RESOLUTION_SCALE
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = False  # Don't generate table images
    
    # Create converter with image extraction options
    doc_converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    
    # Convert the document
    conv_res = doc_converter.convert(str(pdf_path))
    
    return conv_res

def save_base_outputs(conv_res, stem: str):
    """Save the basic markdown and JSON outputs"""
    doc = conv_res.document
    
    # Save markdown (with embedded images)
    md_with_images = OUT_MD / f"{stem}_with_images.md"
    doc.save_as_markdown(md_with_images, image_mode=ImageRefMode.EMBEDDED)
    
    # Save markdown (with image references)
    md_with_refs = OUT_MD / f"{stem}.md"
    doc.save_as_markdown(md_with_refs, image_mode=ImageRefMode.REFERENCED)
    
    # Save HTML with images
    html_path = OUT_MD / f"{stem}.html"
    doc.save_as_html(html_path, image_mode=ImageRefMode.REFERENCED)
    
    # Save JSON (using Docling's export)
    try:
        js = json.loads(doc.model_dump_json(indent=2))
    except:
        js = doc.model_dump() if hasattr(doc, 'model_dump') else doc.dict()
    
    json_path = OUT_JSON / f"{stem}.json"
    json_path.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"  → Saved markdown and JSON outputs")

def extract_page_images(conv_res, stem: str):
    """Extract and save page images"""
    page_dir = OUT_PAGE / stem
    page_dir.mkdir(parents=True, exist_ok=True)
    
    page_count = 0
    for page_no, page in conv_res.document.pages.items():
        if hasattr(page, 'image') and page.image:
            page_image_path = page_dir / f"page_{page.page_no}.png"
            with page_image_path.open("wb") as fp:
                page.image.pil_image.save(fp, format="PNG")
            page_count += 1
    
    if page_count > 0:
        print(f"  → Extracted {page_count} page images to {page_dir}")
    return page_count

def extract_tables(conv_res, stem: str):
    """Extract tables as CSV files only"""
    table_dir = OUT_TAB / stem
    table_dir.mkdir(parents=True, exist_ok=True)
    
    table_count = 0
    for table_idx, table in enumerate(conv_res.document.tables):
        table_count += 1
        
        # Export to DataFrame for CSV
        try:
            table_df = table.export_to_dataframe()
            
            # Save as CSV only
            csv_path = table_dir / f"table_{table_idx + 1}.csv"
            table_df.to_csv(csv_path, index=False)
            
        except Exception as e:
            _log.warning(f"Could not export table {table_idx + 1}: {e}")
    
    if table_count > 0:
        print(f"  → Extracted {table_count} tables as CSV to {table_dir}")
    return table_count

def extract_figures(conv_res, stem: str):
    """Extract only actual figures and charts as images (no tables)"""
    fig_dir = OUT_FIG / stem
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    picture_count = 0
    
    # Iterate through all elements to find ONLY pictures (not tables)
    for element, _level in conv_res.document.iterate_items():
        if isinstance(element, PictureItem):
            picture_count += 1
            image_path = fig_dir / f"figure_{picture_count}.png"
            try:
                with image_path.open("wb") as fp:
                    element.get_image(conv_res.document).save(fp, "PNG")
            except Exception as e:
                _log.warning(f"Could not save figure {picture_count}: {e}")
    
    if picture_count > 0:
        print(f"  → Extracted {picture_count} figures/charts to {fig_dir}")
    
    return picture_count

def extract_layout_info(conv_res, stem: str):
    """Extract and save layout/bounding box information"""
    layout_dir = OUT_LAYOUT / stem
    layout_dir.mkdir(parents=True, exist_ok=True)
    
    doc = conv_res.document
    
    # Collect all layout information
    layout_data = {
        "document": stem,
        "pages": {},
        "text_items": [],
        "tables": [],
        "figures": []
    }
    
    # Extract page dimensions if available
    if hasattr(doc, 'pages'):
        for page_no, page in doc.pages.items():
            layout_data["pages"][str(page_no)] = {
                "page_number": page_no,
                "width": getattr(page, 'width', None),
                "height": getattr(page, 'height', None)
            }
    
    # Extract text items with bounding boxes
    if hasattr(doc, 'texts'):
        for idx, text_item in enumerate(doc.texts):
            if hasattr(text_item, 'prov') and text_item.prov:
                for prov in text_item.prov:
                    if hasattr(prov, 'bbox') and prov.bbox:
                        layout_data["text_items"].append({
                            "index": idx,
                            "text": text_item.text if hasattr(text_item, 'text') else None,
                            "page_no": prov.page_no,
                            "bbox": {
                                "left": prov.bbox.l,
                                "top": prov.bbox.t,
                                "right": prov.bbox.r,
                                "bottom": prov.bbox.b,
                                "coord_origin": prov.bbox.coord_origin if hasattr(prov.bbox, 'coord_origin') else "BOTTOMLEFT"
                            },
                            "type": text_item.obj_type if hasattr(text_item, 'obj_type') else "text"
                        })
    
    # Extract table bounding boxes
    if hasattr(doc, 'tables'):
        for idx, table in enumerate(doc.tables):
            if hasattr(table, 'prov') and table.prov:
                for prov in table.prov:
                    if hasattr(prov, 'bbox') and prov.bbox:
                        layout_data["tables"].append({
                            "index": idx,
                            "page_no": prov.page_no,
                            "bbox": {
                                "left": prov.bbox.l,
                                "top": prov.bbox.t,
                                "right": prov.bbox.r,
                                "bottom": prov.bbox.b,
                                "coord_origin": prov.bbox.coord_origin if hasattr(prov.bbox, 'coord_origin') else "BOTTOMLEFT"
                            }
                        })
    
    # Extract figure/picture bounding boxes
    if hasattr(doc, 'pictures'):
        for idx, picture in enumerate(doc.pictures):
            if hasattr(picture, 'prov') and picture.prov:
                for prov in picture.prov:
                    if hasattr(prov, 'bbox') and prov.bbox:
                        layout_data["figures"].append({
                            "index": idx,
                            "page_no": prov.page_no,
                            "bbox": {
                                "left": prov.bbox.l,
                                "top": prov.bbox.t,
                                "right": prov.bbox.r,
                                "bottom": prov.bbox.b,
                                "coord_origin": prov.bbox.coord_origin if hasattr(prov.bbox, 'coord_origin') else "BOTTOMLEFT"
                            }
                        })
    
    # Save layout data as JSON
    layout_json_path = layout_dir / "layout.json"
    with open(layout_json_path, 'w', encoding='utf-8') as f:
        json.dump(layout_data, f, indent=2, ensure_ascii=False)
    
    # Save layout data as CSV for easy analysis
    rows = []
    for item in layout_data["text_items"]:
        rows.append({
            "type": "text",
            "index": item["index"],
            "page": item["page_no"],
            "left": item["bbox"]["left"],
            "top": item["bbox"]["top"],
            "right": item["bbox"]["right"],
            "bottom": item["bbox"]["bottom"],
            "width": item["bbox"]["right"] - item["bbox"]["left"],
            "height": item["bbox"]["bottom"] - item["bbox"]["top"],
            "text_preview": item["text"][:50] if item["text"] else ""
        })
    
    for item in layout_data["tables"]:
        rows.append({
            "type": "table",
            "index": item["index"],
            "page": item["page_no"],
            "left": item["bbox"]["left"],
            "top": item["bbox"]["top"],
            "right": item["bbox"]["right"],
            "bottom": item["bbox"]["bottom"],
            "width": item["bbox"]["right"] - item["bbox"]["left"],
            "height": item["bbox"]["bottom"] - item["bbox"]["top"],
            "text_preview": f"Table {item['index']}"
        })
    
    for item in layout_data["figures"]:
        rows.append({
            "type": "figure",
            "index": item["index"],
            "page": item["page_no"],
            "left": item["bbox"]["left"],
            "top": item["bbox"]["top"],
            "right": item["bbox"]["right"],
            "bottom": item["bbox"]["bottom"],
            "width": item["bbox"]["right"] - item["bbox"]["left"],
            "height": item["bbox"]["bottom"] - item["bbox"]["top"],
            "text_preview": f"Figure {item['index']}"
        })
    
    if rows:
        df = pd.DataFrame(rows)
        csv_path = layout_dir / "bounding_boxes.csv"
        df.to_csv(csv_path, index=False)
        
        print(f"  → Extracted layout info: {len(rows)} items with bounding boxes")
        print(f"    - JSON: {layout_json_path}")
        print(f"    - CSV: {csv_path}")
    else:
        print(f"  → No layout information found")
    
    return len(rows)

def create_summary(conv_res):
    """Create summary statistics for the document"""
    doc = conv_res.document
    
    # Count different elements
    pages = len(doc.pages) if hasattr(doc, 'pages') else 0
    tables = len(doc.tables) if hasattr(doc, 'tables') else 0
    
    # Count pictures
    pictures = 0
    for element, _ in doc.iterate_items():
        if isinstance(element, PictureItem):
            pictures += 1
    
    # Count text blocks
    blocks = len(list(doc.iterate_items())) if hasattr(doc, 'iterate_items') else 0
    
    return {
        "pages": pages,
        "tables": tables,
        "figures": pictures,
        "blocks": blocks
    }

if __name__ == "__main__":
    # Create output folders (including new layout folder)
    for dir_path in [OUT_MD, OUT_JSON, OUT_TAB, OUT_FIG, OUT_PAGE, OUT_LAYOUT]:
        dir_path.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(IN_DIR.rglob("*.pdf"))
    if not pdfs:
        print("[yellow]No PDFs found in data/upload/ — add files and rerun.[/]")
        raise SystemExit

    print(f"[cyan]Docling (Native Features) — processing {len(pdfs)} PDF(s)[/]")
    print(f"[cyan]Image quality scale: {IMAGE_RESOLUTION_SCALE}x (higher = better quality)[/]\n")
    
    rows = []
    for i, pdf in enumerate(pdfs, start=1):
        stem = pdf.stem
        print(f"[bold][{i}/{len(pdfs)}] Processing: {pdf.name}[/bold]")
        
        start_time = time.time()
        
        # 1) Convert with image extraction enabled
        conv_res = convert_and_extract(pdf)
        
        # 2) Save base outputs (MD, JSON, HTML)
        save_base_outputs(conv_res, stem)
        
        # 3) Extract page images
        extract_page_images(conv_res, stem)
        
        # 4) Extract tables (CSV only)
        extract_tables(conv_res, stem)
        
        # 5) Extract figures and charts
        extract_figures(conv_res, stem)
        
        # 6) Extract layout information with bounding boxes (NEW)
        extract_layout_info(conv_res, stem)
        
        # 7) Create summary
        summary = create_summary(conv_res)
        summary["file"] = pdf.name
        rows.append(summary)
        
        elapsed = time.time() - start_time
        print(f"  → Completed in {elapsed:.1f} seconds\n")
    
    # 8) Write summary CSV
    df = pd.DataFrame(rows)
    df.to_csv(OUT_SUM, index=False)
    
    print(f"[bold green]✓ Processing Complete![/]")
    print(f"[green]Output locations:[/]")
    print(f"  • Markdown      → {OUT_MD}")
    print(f"  • JSON          → {OUT_JSON}")
    print(f"  • Tables        → {OUT_TAB}")
    print(f"  • Figures       → {OUT_FIG}")
    print(f"  • Page Images   → {OUT_PAGE}")
    print(f"  • Layout Info   → {OUT_LAYOUT}")  # NEW
    print(f"  • Summary       → {OUT_SUM}")
    print(f"\n[dim]Tip: Markdown files with '_with_images' have embedded Base64 images[/]")
    print(f"[dim]     Regular .md files reference external image files[/]")
    print(f"[dim]     Layout files contain bounding box coordinates for all elements[/]")  # NEW