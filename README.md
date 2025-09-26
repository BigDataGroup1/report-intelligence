# report-intelligence

**Report Intelligence** is an end-to-end, reproducible pipeline for extracting, parsing, and **validating SEC financial filings** (10-K/10-Q). It automates EDGAR ingestion; runs dual PDF parsers (a fast **pdfplumber** baseline and a layout-aware **Docling** path); attaches provenance (reading order, tables, figures, bounding boxes); and **cross-checks values against XBRL** to flag unit/scale mismatches (e.g., “in millions” vs full dollars). The project includes optional benchmarking with Google Document AI, embeddings for search/QA, and full **DVC** tracking so every result can be reproduced and audited.

---

# PDF Understanding Project — pdfplumber + Docling
> Layout-aware PDF parsing with side-by-side baselines (text, tables, figures, reading order)

## Introduction

This project focuses on the **PDF understanding** component of the pipeline and compares two complementary approaches:

- **Baseline — pdfplumber:** prioritizes native PDF text (with OCR only when necessary), emitting word/line JSONL, baseline table CSVs, and optional figure crops for a quick, scalable extraction path.
- **Unified — Docling:** performs layout detection and **reading-order reconstruction**, exporting clean Markdown/HTML/JSON, robust table DataFrames, figure images, page previews, and **bounding-box provenance** for every element.

Together, these paths produce structured artifacts (Markdown/HTML/JSON, CSV tables, figures, page images, layout CSV/JSON) that you can inspect for fidelity (multi-column flows, borderless tables) and evaluate with text/table metrics. The outcome is a practical recipe: use **pdfplumber** for speed and simple pages; use **Docling** when you need stronger structure and reliable tables—then validate key figures against **XBRL** for correctness.

---

## Project Resources
- 📄 **Report:** `docs/Report.pdf` (or `docs/Report.docx`)
- 🧪 **Sample PDFs:** `data/upload/`
- 🗂️ **Docling Outputs:** `data/parsed/docling/` (md/html/json/tables/figures/pages/layout)
- 🗂️ **pdfplumber Outputs:** `data/parsed/plumber/` (text jsonl/tables/figures/layout)
- 🖼️ **Architecture Diagram:** `architecture/flow_diagram.png`

---

## Technologies
Python • pdfplumber • Docling • Pandas • (optional) Tesseract OCR • (optional) LayoutParser

---

## Architecture Diagram
![Pipeline Diagram](archdiagram.jpg)

---

## Project Flow (4 steps)
1. **Ingest** — Place PDFs in `data/upload/` (subfolders OK).
2. **Parse (Two Paths)** — Run **pdfplumber** baseline and **Docling** unified pipeline.
3. **Export Artifacts** — Save Markdown/HTML/JSON, CSV tables, figures, page images, and layout bboxes.
4. **Summarize** — Generate per-file `summary.csv` for quick counts (pages/tables/figures/blocks).

---

## Repository Structure
