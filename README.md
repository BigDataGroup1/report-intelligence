# report-intelligence
> End-to-end, reproducible pipeline for extracting, parsing, and **validating SEC 10-K/10-Q filings** with dual open-source parsers, optional **Google Document AI** benchmarking, **XBRL** cross-checks, and **DVC** for full reproducibility.

## Introduction
**Report Intelligence** automates EDGAR ingestion and turns raw filings into structured, verifiable data. The project runs two complementary open-source PDF paths (**pdfplumber** baseline and **Docling** unified layout), optionally benchmarks against **Google Document AI**, and validates key figures against **XBRL** to catch scaling/unit mismatches (e.g., “in millions”). All artifacts (Markdown/HTML/JSON, CSV tables, figures, page previews, layout boxes) and metrics are reproducible via **DVC**; embeddings can be built on top for search/QA over the parsed corpus.

**Scope at a glance**
- **Ingestion:** EDGAR download & staging of filings (10-K/10-Q).
- **Parsing (Open-Source):**  
  - **pdfplumber** — fast text-first extraction with optional OCR; baseline tables & word/line JSONL.  
  - **Docling** — layout + reading order; Markdown/HTML/JSON; robust tables, figures, page images, and bounding-box provenance.
- **Parsing (Cloud, optional):** **Google Document AI** for accuracy/runtime/cost comparison.
- **Validation:** **XBRL** cross-checks and unit normalization for high-confidence numeric extraction.
- **Reproducibility:** **DVC** pipelines track data, code, and outputs; embeddings for retrieval/QA (optional).

---

# PDF Understanding Project — pdfplumber + Docling + Google Document AI
> Layout-aware PDF parsing with side-by-side baselines and an optional cloud benchmark.

## Introduction
This project focuses on the **PDF understanding** component of the pipeline and compares three complementary approaches:

- **Baseline — pdfplumber:** prioritizes native PDF text (with OCR only when required), emitting word/line JSONL, baseline table CSVs, and optional figure crops for a fast, scalable path.
- **Unified — Docling:** performs layout detection and **reading-order reconstruction**, exporting clean Markdown/HTML/JSON, reliable table DataFrames, figures, page previews, and element-level **bounding-box provenance**.
- **Benchmark — Google Document AI (optional):** evaluates extraction quality, runtime, and cost against the open-source paths for complex or scanned filings.

Together, these paths produce consistent artifacts (Markdown/HTML/JSON, CSV tables, figures, page images, layout CSV/JSON) that can be inspected for fidelity (multi-column flows, borderless tables) and validated against **XBRL**. Use **pdfplumber** for speed on clean PDFs; use **Docling** when you need stronger structure; **Document AI** serves as an external benchmark on harder documents.


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
