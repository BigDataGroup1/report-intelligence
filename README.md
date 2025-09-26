# report-intelligence
End-to-end pipeline for extracting, parsing, and validating SEC financial filings (10-K/10-Q) using Python. Includes text/OCR, table extraction, layout detection, embeddings, and XBRL validation with reproducible DVC workflows.
# PDF Understanding Lab — pdfplumber + Docling
> Layout-aware PDF parsing with side-by-side baselines (text, tables, figures, reading order)

## Introduction
This project builds a reproducible pipeline to parse PDFs using two complementary approaches:
- **Baseline:** `pdfplumber` for fast text and simple table extraction.
- **Unified:** **Docling** for reading-order Markdown/HTML/JSON, reliable tables, figures, page previews, and bounding boxes.

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
![Pipeline Diagram](archdiagram.png)

---

## Project Flow (4 steps)
1. **Ingest** — Place PDFs in `data/upload/` (subfolders OK).
2. **Parse (Two Paths)** — Run **pdfplumber** baseline and **Docling** unified pipeline.
3. **Export Artifacts** — Save Markdown/HTML/JSON, CSV tables, figures, page images, and layout bboxes.
4. **Summarize** — Generate per-file `summary.csv` for quick counts (pages/tables/figures/blocks).

---

## Repository Structure
