#!/usr/bin/env python3
import argparse
import base64
import difflib
import html as html_module
import json
import math
import re
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import markdown2

# Try to import Playwright (optional, recommended on Windows)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# -------------------- FOLDERS --------------------
UPLOADS_DIR        = Path("data/upload")
PARSED_DIR         = Path("data/parsed")
DOCLING_MD_DIR     = PARSED_DIR / "docling" / "md"
DOCLING_JSON_DIR   = PARSED_DIR / "docling" / "json"
STAGED_DIR         = Path("data/staged")

# -------------------- UTIL -----------------------
def must_exist(p: Path, label: str):
    if not p.exists():
        raise FileNotFoundError(f"Required {label} not found: {p}")
    return p

def ensure_parent(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9.\-/$%]+", (s or "").lower())

def jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    if not A and not B: return 1.0
    return len(A & B) / max(1, len(A | B))

def prec_recall_f1(ref: List[str], hyp: List[str]) -> Tuple[float,float,float]:
    A, B = set(ref), set(hyp)
    tp = len(A & B)
    p  = tp / len(B) if B else 1.0
    r  = tp / len(A) if A else 1.0
    f1 = (2*p*r / (p+r)) if (p+r) else 1.0
    return p, r, f1

def render_pdf_page(pdf_path: Path, page_num: int, dpi=200) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    if page_num < 1 or page_num > len(doc):
        raise IndexError(f"Page {page_num} out of range (1..{len(doc)}) for {pdf_path}")
    page = doc[page_num-1]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

def load_layout(doc_id: str, page: int) -> dict:
    p = PARSED_DIR / doc_id / "layout" / f"page_{page}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"blocks": [], "backend": "missing"}

def load_words_jsonl(doc_id: str, page: int) -> List[Dict[str,Any]]:
    p = PARSED_DIR / doc_id / f"{doc_id}_words.jsonl"
    if not p.exists(): return []
    out = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if int(rec.get("page", -1)) == page:
                    out.append(rec)
            except Exception:
                continue
    return out

def pipeline_figures_for_page(doc_id: str, page: int) -> List[Path]:
    d = PARSED_DIR / doc_id / "figures" / f"page_{page}"
    if not d.exists(): return []
    return sorted(d.glob("figure_*.png"))

# -------------------- ENHANCED DOCLING IMAGE RESOLUTION --------------------
def unquote_src(src: str) -> str:
    s = urllib.parse.unquote(src or "")
    return s.replace("\\", "/")

def find_image_in_artifacts(basename: str, doc_id: str) -> Optional[Path]:
    """
    Search for an image file in the docling artifacts directory.
    Priority order:
    1. Check in doc_id specific artifacts folder
    2. Check in general docling/md folder
    3. Global search under PARSED_DIR
    """
    # First check in document-specific artifacts folder
    doc_artifacts = DOCLING_MD_DIR / f"{doc_id}_artifacts"
    if doc_artifacts.exists():
        candidate = doc_artifacts / basename
        if candidate.exists():
            return candidate
    
    # Check in general docling/md folder with wildcard pattern
    for pattern in [f"*_artifacts/{basename}", f"*/{basename}", basename]:
        for candidate in DOCLING_MD_DIR.glob(pattern):
            if candidate.is_file():
                return candidate
    
    # Global search as last resort
    for candidate in PARSED_DIR.rglob(basename):
        if candidate.is_file():
            return candidate
    
    return None

def resolve_src_to_file_uri(src: str, base_dir: Path, doc_id: str = None) -> str:
    """
    Resolve an image src to a usable URI with improved docling support.
    """
    s = unquote_src(src).strip()
    if not s:
        return src
    
    # Return data URIs and URLs as-is
    if s.startswith(("data:", "http://", "https://", "file:")):
        return s
    
    # Parse the path to handle Windows-style paths
    normalized_path = s.replace("\\", "/")
    
    # Try as absolute path first
    p = Path(s)
    if p.is_absolute() and p.exists():
        return p.resolve().as_uri()
    
    # Try relative to base_dir
    if base_dir:
        rel_path = base_dir / normalized_path
        if rel_path.exists():
            return rel_path.resolve().as_uri()
    
    # Extract basename for artifact search
    basename = Path(normalized_path).name
    
    # If we have a doc_id, use it for targeted search
    if doc_id and basename:
        found = find_image_in_artifacts(basename, doc_id)
        if found:
            return found.resolve().as_uri()
    
    # If no doc_id, just search by basename
    elif basename:
        for candidate in PARSED_DIR.rglob(basename):
            if candidate.is_file():
                return candidate.resolve().as_uri()
    
    # Last resort: check if the path contains "artifacts" and extract the image name
    if "_artifacts" in normalized_path and basename:
        for candidate in PARSED_DIR.rglob(basename):
            if "_artifacts" in str(candidate):
                return candidate.resolve().as_uri()
    
    return src

def fix_markdown_image_paths(md_text: str, base_dir: Path, doc_id: str) -> str:
    """
    Pre-process markdown to fix image references before HTML conversion.
    """
    # Fix markdown image syntax ![alt](path)
    def fix_md_image(m):
        alt = m.group(1) or ""
        src = m.group(2)
        new_src = resolve_src_to_file_uri(src, base_dir, doc_id)
        return f"![{alt}]({new_src})"
    
    md_text = re.sub(r'!\[(.*?)\]\((.*?)\)', fix_md_image, md_text)
    
    # Also fix any HTML img tags that might be in the markdown
    def fix_html_img(m):
        tag_content = m.group(1)
        def fix_src(src_m):
            src = src_m.group(1)
            new_src = resolve_src_to_file_uri(src, base_dir, doc_id)
            return f'src="{new_src}"'
        
        fixed_tag = re.sub(r'src=["\'](.*?)["\']', fix_src, tag_content, flags=re.I)
        return f"<img{fixed_tag}>"
    
    md_text = re.sub(r'<img(.*?)>', fix_html_img, md_text, flags=re.I|re.S)
    
    return md_text

def rewrite_image_srcs_in_html(html_text: str, base_dir: Path, doc_id: str = None) -> str:
    """
    Find all src="..." occurrences and convert to absolute file:// URIs.
    """
    def repl(m):
        src = m.group(1)
        new = resolve_src_to_file_uri(src, base_dir, doc_id)
        return f'src="{html_module.escape(new)}"'
    
    return re.sub(r'src=["\'](.*?)["\']', repl, html_text, flags=re.I|re.S)

# -------------------- DOC/MD/HTML LOADER --------------------
def find_docling_sources(doc_id: str):
    """
    Return tuple (kind, path) where kind in {"md_embedded","html","md","json"}
    """
    md_emb = DOCLING_MD_DIR / f"{doc_id}_with_images.md"
    html_f = DOCLING_MD_DIR / f"{doc_id}.html"
    md_f   = DOCLING_MD_DIR / f"{doc_id}.md"
    json_f = DOCLING_JSON_DIR / f"{doc_id}.json"

    if md_emb.exists():
        return "md_embedded", md_emb
    if html_f.exists():
        return "html", html_f
    if md_f.exists():
        return "md", md_f
    if json_f.exists():
        return "json", json_f
    return None, None

def load_docling_as_html(doc_id: str) -> Tuple[Optional[str], Optional[Path], str]:
    """
    Load the docling output and return (html_content, base_dir, mode)
    """
    kind, p = find_docling_sources(doc_id)
    if not p:
        return None, None, ""
    
    base_dir = p.parent
    
    if kind == "md_embedded":
        md_text = p.read_text(encoding="utf-8")
        fixed_md = fix_markdown_image_paths(md_text, base_dir, doc_id)
        html = markdown2.markdown(fixed_md, extras=["tables", "fenced-code-blocks"])
        html_fixed = rewrite_image_srcs_in_html(html, base_dir, doc_id)
        return html_fixed, base_dir, "md_embedded"
    
    if kind == "html":
        html_text = p.read_text(encoding="utf-8")
        html_fixed = rewrite_image_srcs_in_html(html_text, base_dir, doc_id)
        return html_fixed, base_dir, "html"
    
    if kind == "md":
        md_text = p.read_text(encoding="utf-8")
        fixed_md = fix_markdown_image_paths(md_text, base_dir, doc_id)
        html = markdown2.markdown(fixed_md, extras=["tables", "fenced-code-blocks"])
        html_fixed = rewrite_image_srcs_in_html(html, base_dir, doc_id)
        return html_fixed, base_dir, "md"
    
    if kind == "json":
        try:
            js = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            js = None
        text = ""
        if js:
            def walk(n):
                nonlocal text
                if isinstance(n, dict):
                    for k,v in n.items():
                        if k in ("text","content") and isinstance(v, str):
                            text += v + "\n"
                        else:
                            walk(v)
                elif isinstance(n, list):
                    for el in n:
                        walk(el)
            walk(js)
        html = "<pre>" + html_module.escape(text) + "</pre>"
        return html, base_dir, "json"
    
    return None, None, ""

# -------------------- RENDER HTML to IMAGE --------------------
def render_html_with_playwright(html_content: str, base_dir: Path, base_w: int, base_h: int, timeout_ms:int=30000) -> Image.Image:
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright not available")

    base_uri = (base_dir.resolve().as_uri() + "/") if base_dir else (Path.cwd().resolve().as_uri() + "/")
    html_with_base = f'<base href="{base_uri}"/>\n' + html_content

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": base_w, "height": base_h})
        page.set_content(html_with_base, wait_until="networkidle", timeout=timeout_ms)
        shot = page.screenshot(full_page=False)
        browser.close()

    img = Image.open(BytesIO(shot)).convert("RGB")
    img = img.resize((base_w, base_h), Image.LANCZOS)
    return img

def decode_data_uri_image(data_uri: str) -> Optional[Image.Image]:
    m = re.match(r"data:(image/[\w+.-]+);base64,(.*)$", data_uri, flags=re.I|re.S)
    if not m:
        return None
    b64 = m.group(2)
    try:
        raw = base64.b64decode(b64)
        return Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return None

def fallback_render_html_as_image_enhanced(html_content: str, base_dir: Path, base_w: int, base_h: int, doc_id: str = None) -> Image.Image:
    """
    Enhanced fallback renderer that properly clips content to page boundaries
    """
    img = Image.new("RGB", (base_w, base_h), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except:
        try:
            font = ImageFont.load_default()
        except:
            font = None
    
    # Extract just the body content if it's a full HTML document
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if body_match:
        content = body_match.group(1)
    else:
        content = html_content
    
    # Split by various block elements, not just images
    parts = re.split(r'(<(?:img|table|figure|div|p|h[1-6])\b[^>]*>.*?</(?:img|table|figure|div|p|h[1-6])>|<img\b[^>]*>)', 
                     content, flags=re.I|re.S)
    
    x_margin = 40
    x = x_margin
    y = 40
    line_h = 16
    max_width = base_w - (2 * x_margin)
    
    for part in parts:
        if y > base_h - 40:
            # Stop rendering when we reach the bottom of the page
            break
            
        part = part.strip()
        if not part:
            continue
        
        # Handle images
        if re.match(r'<img\b', part, re.I):
            src_m = re.search(r'src=["\'](.*?)["\']', part, flags=re.I|re.S)
            if src_m:
                src = src_m.group(1)
                im = None
                
                if src.startswith("data:"):
                    im = decode_data_uri_image(src)
                elif src.startswith("file://"):
                    try:
                        p = Path(urllib.parse.urlparse(src).path)
                        if not p.exists() and p.as_posix().startswith("/"):
                            p = Path(p.as_posix().lstrip("/"))
                        if p.exists():
                            im = Image.open(p).convert("RGB")
                    except Exception as e:
                        print(f"Failed to load image from {src}: {e}")
                else:
                    basename = Path(src).name
                    if basename and doc_id:
                        found = find_image_in_artifacts(basename, doc_id)
                        if found:
                            try:
                                im = Image.open(found).convert("RGB")
                            except Exception as e:
                                print(f"Failed to load artifact {found}: {e}")
                
                if im:
                    # Scale image to fit within bounds
                    max_img_w = max_width
                    max_img_h = min(base_h // 4, base_h - y - 40)  # Don't let image take more than 1/4 of page
                    
                    img_w, img_h = im.size
                    scale = min(max_img_w / img_w, max_img_h / img_h, 1.0)  # Don't upscale
                    
                    if scale < 1.0:
                        new_w = int(img_w * scale)
                        new_h = int(img_h * scale)
                        im = im.resize((new_w, new_h), Image.LANCZOS)
                    
                    # Center the image horizontally
                    img_x = x + (max_width - im.width) // 2
                    img.paste(im, (img_x, y))
                    y += im.height + 12
                else:
                    draw.rectangle([x, y, x+100, y+60], outline=(200,200,200), width=1)
                    draw.text((x+5, y+20), "[Image]", fill=(150,150,150), font=font)
                    y += 70
        
        # Handle tables
        elif '<table' in part.lower():
            # Extract table text roughly
            table_text = re.sub(r'<[^>]+>', '\t', part)
            table_text = html_module.unescape(table_text)
            table_text = re.sub(r'\t+', '\t', table_text)
            table_text = re.sub(r'\n+', '\n', table_text).strip()
            
            # Draw a table placeholder with some content
            draw.rectangle([x, y, base_w - x_margin, min(y + 100, base_h - 40)], 
                          outline=(100, 100, 200), width=1)
            
            # Add first few lines of table content
            table_y = y + 5
            for table_line in table_text.split('\n')[:4]:  # Show first 4 rows
                if table_y > min(y + 95, base_h - 45):
                    break
                if table_line.strip():
                    # Truncate long lines
                    if len(table_line) > 100:
                        table_line = table_line[:100] + "..."
                    draw.text((x + 5, table_y), table_line[:100], fill=(50, 50, 150), font=font)
                    table_y += line_h
            
            y = min(y + 105, base_h - 40)
        
        # Handle other text content
        else:
            # Clean up text
            txt = re.sub(r"<script.*?>.*?</script>", "", part, flags=re.S|re.I)
            txt = re.sub(r"<style.*?>.*?</style>", "", txt, flags=re.S|re.I)
            
            # Handle headers
            h_match = re.match(r'<h([1-6])\b[^>]*>(.*?)</h\1>', txt, re.I|re.S)
            if h_match:
                level = int(h_match.group(1))
                header_text = re.sub(r'<[^>]+>', '', h_match.group(2))
                header_text = html_module.unescape(header_text).strip()
                
                if header_text:
                    # Make headers bold/larger
                    try:
                        header_size = 16 + (6 - level) * 2
                        header_font = ImageFont.truetype("arial.ttf", header_size)
                    except:
                        header_font = font
                    
                    y += 6  # Add space before header
                    draw.text((x, y), header_text[:80], fill=(0, 0, 0), font=header_font)
                    y += line_h + 8  # Add space after header
                continue
            
            # Regular text
            txt = re.sub(r"<[^>]+>", " ", txt)
            txt = html_module.unescape(txt)
            
            paragraphs = txt.split('\n')
            for para in paragraphs:
                para = para.strip()
                if not para:
                    y += 6  # Blank line
                    continue
                
                # Word wrap the paragraph
                words = para.split()
                lines = []
                current_line = []
                current_length = 0
                
                for word in words:
                    word_length = len(word)
                    if current_length + word_length + 1 > 100:  # Approximate line width
                        if current_line:
                            lines.append(' '.join(current_line))
                        current_line = [word]
                        current_length = word_length
                    else:
                        current_line.append(word)
                        current_length += word_length + 1
                
                if current_line:
                    lines.append(' '.join(current_line))
                
                for line in lines:
                    if y > base_h - 40:
                        break
                    if line:
                        draw.text((x, y), line, fill=(0, 0, 0), font=font)
                        y += line_h
                
                y += 4  # Small space between paragraphs
    
    return img


# -------------------- DOCLING RECONSTRUCTION --------------------
def reconstruct_docling_page(doc_id: str, page: int, base_w: int, base_h: int) -> Tuple[Image.Image, Dict[str,Any], str]:
    """
    Simplified reconstruction that reads actual page text and shows it properly
    """
    # First, try to get the actual page text from parsed directory
    parsed_dir = PARSED_DIR / doc_id
    page_text_file = parsed_dir / "pages" / f"page_{page}.txt"
    
    # Also check for tables and figures for this page
    tables_dir = parsed_dir / "tables"
    figures_dir = parsed_dir / "figures" / f"page_{page}"
    
    # Start building HTML content
    page_html_parts = [
        '<html><body style="padding: 20px; font-family: Arial, sans-serif;">',
        f'<h2 style="color: #333;">Docling - Page {page}</h2>'
    ]
    
    page_text_content = ""
    tables_count = 0
    figures_count = 0
    
    # 1. Load and display the page text
    if page_text_file.exists():
        try:
            page_text_content = page_text_file.read_text(encoding='utf-8')
            
            # Clean and format the text
            lines = page_text_content.split('\n')
            
            # Add text content with proper formatting
            page_html_parts.append('<div style="margin: 20px 0;">')
            
            for line in lines[:50]:  # Show first 50 lines to fit on page
                line = line.strip()
                if line:
                    # Check if it looks like a header (all caps or starts with number)
                    if line.isupper() and len(line) < 100:
                        page_html_parts.append(f'<h3 style="color: #0066cc;">{html_module.escape(line)}</h3>')
                    elif line[0:1].isdigit() and '.' in line[:4]:
                        page_html_parts.append(f'<h4 style="color: #666;">{html_module.escape(line)}</h4>')
                    else:
                        # Regular paragraph
                        if len(line) > 200:
                            line = line[:200] + "..."
                        page_html_parts.append(f'<p style="margin: 5px 0;">{html_module.escape(line)}</p>')
            
            if len(lines) > 50:
                page_html_parts.append(f'<p style="color: #999; font-style: italic;">... and {len(lines) - 50} more lines</p>')
            
            page_html_parts.append('</div>')
            
        except Exception as e:
            page_html_parts.append(f'<p style="color: red;">Error loading page text: {e}</p>')
    else:
        page_html_parts.append(f'<p style="color: #999;">No text file found at {page_text_file}</p>')
    
    # 2. Check for tables on this page
    if tables_dir.exists():
        table_files = list(tables_dir.glob(f"table_p{page}_*.csv"))
        if table_files:
            page_html_parts.append(f'<h3 style="color: #0066cc;">Tables on Page {page}</h3>')
            for table_file in table_files[:3]:  # Show first 3 tables
                tables_count += 1
                try:
                    import pandas as pd
                    df = pd.read_csv(table_file)
                    page_html_parts.append(f'<div style="border: 2px solid #0066cc; padding: 10px; margin: 10px 0;">')
                    page_html_parts.append(f'<h4>Table {tables_count}: {table_file.stem}</h4>')
                    
                    # Show table preview (first 3 rows, first 5 columns)
                    preview_df = df.iloc[:3, :5] if len(df) > 3 else df.iloc[:, :5]
                    table_html = preview_df.to_html(index=False)
                    page_html_parts.append(table_html)
                    page_html_parts.append(f'<p style="color: #666; font-size: 0.9em;">Shape: {df.shape[0]} rows × {df.shape[1]} columns</p>')
                    page_html_parts.append('</div>')
                except Exception as e:
                    page_html_parts.append(f'<div style="border: 1px solid #ccc; padding: 5px;">Table {tables_count} - Load error</div>')
    
    # 3. Check for figures on this page
    if figures_dir.exists():
        figure_files = list(figures_dir.glob("figure_*.png"))
        if figure_files:
            page_html_parts.append(f'<h3 style="color: #0066cc;">Figures on Page {page}</h3>')
            for fig_file in figure_files[:2]:  # Show first 2 figures
                figures_count += 1
                try:
                    # Convert to base64 for embedding
                    import base64
                    with open(fig_file, 'rb') as f:
                        img_data = base64.b64encode(f.read()).decode()
                    page_html_parts.append(f'<div style="border: 2px solid #cc0000; padding: 10px; margin: 10px 0;">')
                    page_html_parts.append(f'<h4>Figure {figures_count}</h4>')
                    page_html_parts.append(f'<img src="data:image/png;base64,{img_data}" style="max-width: 100%; max-height: 200px;"/>')
                    page_html_parts.append('</div>')
                except:
                    page_html_parts.append(f'<div style="border: 1px solid #ccc; padding: 5px;">Figure {figures_count} - Load error</div>')
    
    # Add summary
    page_html_parts.append('<hr style="margin: 20px 0;"/>')
    page_html_parts.append('<div style="background: #f5f5f5; padding: 10px; border-radius: 5px;">')
    page_html_parts.append(f'<strong>Page {page} Summary:</strong><br/>')
    page_html_parts.append(f'Text lines: {len(page_text_content.split(chr(10))) if page_text_content else 0}<br/>')
    page_html_parts.append(f'Tables: {tables_count}<br/>')
    page_html_parts.append(f'Figures: {figures_count}')
    page_html_parts.append('</div>')
    
    page_html_parts.append('</body></html>')
    page_html = '\n'.join(page_html_parts)
    
    # Render the HTML
    img = Image.new("RGB", (base_w, base_h), color="white")
    
    if PLAYWRIGHT_AVAILABLE:
        try:
            img = render_html_with_playwright(page_html, Path("."), base_w, base_h, timeout_ms=10000)
        except Exception as e:
            print(f"Playwright rendering failed: {e}, using fallback")
            img = fallback_render_html_as_image_enhanced(page_html, Path("."), base_w, base_h, doc_id)
    else:
        img = fallback_render_html_as_image_enhanced(page_html, Path("."), base_w, base_h, doc_id)
    
    stats = {
        "mode": "simplified_page_reconstruction",
        "tables": tables_count,
        "figures": figures_count,
        "text_tokens": len(tokens(page_text_content))
    }
    
    return img, stats, page_text_content[:1000]
    # Keep the rest of your original fallback code as is
    # ... (rest of the original function)

# -------------------- PIPELINE RECONSTRUCTION --------------------
def draw_text_wordwise(img: Image.Image, words: List[Dict[str,Any]], font_size=14):
    W, H = img.size
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.load_default()
    except Exception: font = None
    for w in words:
        t = (w.get("word") or "").strip()
        if not t: continue
        bb = w.get("bbox_norm") or {}
        x0 = int((bb.get("x0", 0))*W); y0 = int((bb.get("y0", 0))*H)
        x1 = int((bb.get("x1", 0))*W); y1 = int((bb.get("y1", 0))*H)
        y_text = max(y0, y1 - font_size)
        draw.text((x0, y_text), t, fill=(0,0,0), font=font)

def draw_tables_placeholders(img: Image.Image, layout: dict):
    W, H = img.size
    draw = ImageDraw.Draw(img)
    for b in (layout.get("blocks") or []):
        if b.get("type") != "Table": continue
        bb = b.get("bbox_norm") or {}
        x0 = int(bb.get("x0",0)*W); y0 = int(bb.get("y0",0)*H)
        x1 = int(bb.get("x1",0)*W); y1 = int(bb.get("y1",0)*H)
        draw.rectangle([x0,y0,x1,y1], outline=(0,0,255), width=3)
        draw.text((x0+5, y0+5), "[TABLE]", fill=(0,0,255))

def paste_figures(img: Image.Image, doc_id: str, page: int, layout: dict):
    W, H = img.size
    draw = ImageDraw.Draw(img)
    crops = pipeline_figures_for_page(doc_id, page)
    figure_boxes = []
    for b in (layout.get("blocks") or []):
        if b.get("type") == "Figure":
            bb = b.get("bbox_norm") or {}
            x0 = int(bb.get("x0",0)*W); y0 = int(bb.get("y0",0)*H)
            x1 = int(bb.get("x1",0)*W); y1 = int(bb.get("y1",0)*H)
            figure_boxes.append((x0,y0,x1,y1))
    for idx, box in enumerate(figure_boxes):
        if idx < len(crops):
            crop = Image.open(crops[idx]).convert("RGB")
            crop_resized = crop.resize((box[2]-box[0], box[3]-box[1]))
            img.paste(crop_resized, box[:2])
        else:
            draw.rectangle(box, outline=(255,0,0), width=3)
            draw.text((box[0]+5, box[1]+5), "[FIGURE?]", fill=(255,0,0))

def reconstruct_pipeline_page(doc_id: str, page: int, base_w: int, base_h: int) -> Image.Image:
    canvas = Image.new("RGB", (base_w, base_h), color="white")
    words  = load_words_jsonl(doc_id, page)
    layout = load_layout(doc_id, page)
    draw_text_wordwise(canvas, words, font_size=14)
    draw_tables_placeholders(canvas, layout)
    paste_figures(canvas, doc_id, page, layout)
    return canvas

# -------------------- COMPOSITION & REPORT --------------------
def concat_side_by_side(imgs: List[Image.Image], pad=10, bg=(240,240,240)) -> Image.Image:
    H = max(im.height for im in imgs)
    W = sum(im.width for im in imgs) + pad*(len(imgs)-1)
    canvas = Image.new("RGB", (W, H), color=bg)
    x = 0
    for im in imgs:
        canvas.paste(im, (x, 0)); x += im.width + pad
    return canvas

def make_summary_panel(w: int, h: int, lines: List[str]) -> Image.Image:
    img = Image.new("RGB", (w, h), color="white")
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.load_default()
    except Exception: font = None
    x, y = 40, 40
    for L in lines:
        for ln in textwrap.wrap(L, width=100):
            draw.text((x, y), ln, fill=(0,0,0), font=font)
            y += 18
        y += 6
    return img

def save_pdf(png_paths: List[Path], out_pdf: Path):
    pages = [Image.open(p).convert("RGB") for p in png_paths if p.exists()]
    if not pages: return
    ensure_parent(out_pdf)
    first, rest = pages[0], pages[1:]
    first.save(out_pdf, "PDF", resolution=200.0, save_all=True, append_images=rest)

# -------------------- MAIN --------------------
def main():
    ap = argparse.ArgumentParser(description="Reconstruct Docling & Pipeline page and compare with original PDF.")
    ap.add_argument("--doc", required=True, help="Document ID, e.g., Apple_SEA")
    ap.add_argument("--page", type=int, required=True, help="1-based page number")
    args = ap.parse_args()

    doc_id, page = args.doc, args.page
    pdf_path = must_exist(UPLOADS_DIR / f"{doc_id}.pdf", "PDF")

    print(f"[1/6] Rendering original p.{page} …")
    orig = render_pdf_page(pdf_path, page, dpi=200)
    W, H = orig.size
    orig_out = STAGED_DIR / f"{doc_id}_page_{page}_original.png"
    ensure_parent(orig_out); orig.save(orig_out)

    print("[2/6] Reconstructing pipeline …")
    pipe = reconstruct_pipeline_page(doc_id, page, W, H)
    pipe_out = STAGED_DIR / f"{doc_id}_page_{page}_pipeline_recon.png"
    pipe.save(pipe_out)

    print("[3/6] Reconstructing Docling …")
    doc_img, doc_stats, doc_text = reconstruct_docling_page(doc_id, page, W, H)
    doc_out = STAGED_DIR / f"{doc_id}_page_{page}_docling_recon.png"
    doc_img.save(doc_out)

    print("[4/6] Side-by-side panel …")
    sbs = concat_side_by_side([orig, pipe, doc_img])
    sbs_out = STAGED_DIR / f"{doc_id}_page_{page}_side_by_side.png"
    sbs.save(sbs_out)

    print("[5/6] Scoring …")
    words = load_words_jsonl(doc_id, page)
    pipe_text = " ".join((w.get("word") or "") for w in words)
    t_pipe = tokens(pipe_text); t_doc = tokens(doc_text)

    j = jaccard(t_pipe, t_doc)
    p, r, f1 = prec_recall_f1(t_pipe, t_doc)

    layout = load_layout(doc_id, page)
    pipe_tables = sum(1 for b in layout.get("blocks", []) if b.get("type") == "Table")
    pipe_figs   = sum(1 for b in layout.get("blocks", []) if b.get("type") == "Figure")
    doc_tables  = int(doc_stats.get("tables", 0)); doc_figs = int(doc_stats.get("figures", 0))

    table_match = 1.0 if pipe_tables == doc_tables else max(0.0, 1.0 - abs(pipe_tables - doc_tables)/max(1, pipe_tables))
    figure_match = 1.0 if pipe_figs   == doc_figs   else max(0.0, 1.0 - abs(pipe_figs   - doc_figs  )/max(1, pipe_figs))
    score = 100.0*(0.70*f1 + 0.15*table_match + 0.15*figure_match)

    print("[6/6] Summary page + PDF …")
    summary_lines = [
        f"{doc_id} — page {page} comparison",
        "",
        f"Docling mode: {doc_stats.get('mode')}",
        f"Text Jaccard: {j:.3f}",
        f"Text Precision: {p:.3f}  Recall: {r:.3f}  F1: {f1:.3f}",
        f"Tables — pipeline: {pipe_tables} | docling: {doc_tables}",
        f"Figures — pipeline: {pipe_figs} | docling: {doc_figs}",
        "",
        f"Composite Score (0..100): {score:.1f}",
        "",
        "Legend:",
        "- Left = Original PDF page",
        "- Middle = Pipeline reconstruction (blue=[TABLE], red=[FIGURE], text from words.jsonl)",
        "- Right = Docling reconstruction (rendered HTML/Markdown snapshot)",
    ]
    summary = make_summary_panel(W, H, summary_lines)
    summary_out = STAGED_DIR / f"{doc_id}_page_{page}_summary.png"
    summary.save(summary_out)

    pdf_out = STAGED_DIR / f"{doc_id}_page_{page}_comparison.pdf"
    save_pdf([orig_out, pipe_out, doc_out, sbs_out, summary_out], pdf_out)

    diff_lines = list(difflib.unified_diff(
        pipe_text.splitlines(), (doc_text or "").splitlines(),
        fromfile="pipeline", tofile="docling", lineterm=""
    ))
    diff_preview = "\n".join(diff_lines[:200]) if diff_lines else "(texts very similar or one side empty)"

    md = STAGED_DIR / f"{doc_id}_page_{page}_comparison.md"
    md.write_text("\n".join([
        f"# {doc_id} — page {page} comparison",
        "",
        f"- Original: `{orig_out}`",
        f"- Pipeline: `{pipe_out}`",
        f"- Docling: `{doc_out}`",
        f"- Side-by-side: `{sbs_out}`",
        f"- Summary: `{summary_out}`",
        f"- PDF: `{pdf_out}`",
        "",
        f"- Docling mode: **{doc_stats.get('mode')}**",
        f"- Text Jaccard: **{j:.3f}**",
        f"- Precision: **{p:.3f}**, Recall: **{r:.3f}**, F1: **{f1:.3f}**",
        f"- Tables → pipeline: **{pipe_tables}**, docling: **{doc_tables}**",
        f"- Figures → pipeline: **{pipe_figs}**, docling: **{doc_figs}**",
        f"- Composite score: **{score:.1f}** / 100",
        "",
        "## Diff preview (pipeline vs docling)",
        "```diff",
        diff_preview,
        "```"
    ]), encoding="utf-8")

    print(f"✓ Wrote images + {pdf_out} and markdown report")
    print("Done.")
    print("Outputs:")
    print(" -", orig_out)
    print(" -", pipe_out)
    print(" -", doc_out)
    print(" -", sbs_out)
    print(" -", summary_out)
    print(" -", pdf_out)
    print(" -", md)

if __name__ == "__main__":
    main()