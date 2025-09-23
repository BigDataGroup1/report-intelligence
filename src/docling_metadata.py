#!/usr/bin/env python
"""
Part 5 - Enhanced Metadata & Provenance Tagging
Combines data from ALL Docling outputs to create comprehensive metadata

Reads from:
- json/: Main document structure
- layout/: Bounding boxes CSV and layout JSON
- tables/: Individual table CSV files
- figures/: Extracted figure PNG files
- md/: Markdown outputs

Creates:
- metadata/*.jsonl: Complete provenance records
- sections/*.md: Section summaries
"""

import json
import csv
import os
from pathlib import Path
from typing import Dict, List, Any
import hashlib
from datetime import datetime
import pandas as pd
import re

class EnhancedDoclingMetadataProcessor:
    def __init__(self, base_path: str = "data/parsed/docling"):
        """Initialize processor with Docling base path"""
        self.base_path = Path(base_path)
        
        # Input directories
        self.json_dir = self.base_path / "json"
        self.layout_dir = self.base_path / "layout"
        self.tables_dir = self.base_path / "tables"
        self.figures_dir = self.base_path / "figures"
        self.pages_dir = self.base_path / "pages"
        self.md_dir = self.base_path / "md"
        
        # Output directories
        self.metadata_dir = self.base_path / "metadata"
        self.sections_dir = self.base_path / "sections"
        
        # Create output directories
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.sections_dir.mkdir(parents=True, exist_ok=True)
    
    def load_bounding_boxes_csv(self, doc_name: str) -> Dict:
        """Load bounding boxes from CSV file"""
        bbox_csv = self.layout_dir / doc_name / "bounding_boxes.csv"
        bbox_dict = {}
        
        if bbox_csv.exists():
            df = pd.read_csv(bbox_csv)
            for _, row in df.iterrows():
                # Create key based on type and index
                key = f"{row['type']}_{row['index']}"
                bbox_dict[key] = {
                    "page": row['page'],
                    "left": row['left'],
                    "top": row['top'],
                    "right": row['right'],
                    "bottom": row['bottom'],
                    "width": row.get('width', row['right'] - row['left']),
                    "height": row.get('height', row['bottom'] - row['top'])
                }
        
        return bbox_dict
    
    def load_layout_json(self, doc_name: str) -> Dict:
        """Load layout JSON with additional structure info"""
        layout_json = self.layout_dir / doc_name / "layout.json"
        if layout_json.exists():
            with open(layout_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def load_table_csv(self, doc_name: str, table_idx: int) -> Dict:
        """Load actual table data from CSV"""
        table_csv = self.tables_dir / doc_name / f"table_{table_idx + 1}.csv"
        table_data = {
            "exists": False,
            "rows": 0,
            "columns": 0,
            "data": [],
            "preview": ""
        }
        
        if table_csv.exists():
            try:
                df = pd.read_csv(table_csv)
                table_data["exists"] = True
                table_data["rows"] = len(df)
                table_data["columns"] = len(df.columns)
                table_data["data"] = df.to_dict('records')
                
                # Create preview (first 3 rows)
                preview_rows = []
                preview_rows.append(" | ".join(str(col) for col in df.columns))
                for idx, row in df.head(3).iterrows():
                    preview_rows.append(" | ".join(str(val) for val in row.values))
                table_data["preview"] = "\n".join(preview_rows)
                
            except Exception as e:
                print(f"    Warning: Could not load table CSV: {e}")
        
        return table_data
    
    def check_figure_exists(self, doc_name: str, figure_idx: int) -> Dict:
        """Check if figure PNG exists and get info"""
        figure_png = self.figures_dir / doc_name / f"figure_{figure_idx + 1}.png"
        figure_info = {
            "exists": figure_png.exists(),
            "path": str(figure_png) if figure_png.exists() else None,
            "size": figure_png.stat().st_size if figure_png.exists() else 0
        }
        return figure_info
    
    def extract_company_info(self, doc_name: str) -> Dict:
        """Extract company and filing information"""
        info = {
            "company": "UNKNOWN",
            "fiscal_year": "2024",
            "filing_type": "UNKNOWN"
        }
        
        # Clean name
        clean = doc_name.replace("_SEA", "").replace("_10K", "").replace("_10Q", "")
        parts = re.split(r'[_\-]', clean)
        
        if parts:
            info["company"] = parts[0]
        
        # Check for filing type
        filing_types = ["10K", "10Q", "8K", "SEA", "20F"]
        for ft in filing_types:
            if ft in doc_name.upper():
                info["filing_type"] = ft
                break
        
        # Extract year
        year_match = re.search(r'20[12]\d', doc_name)
        if year_match:
            info["fiscal_year"] = year_match.group()
        
        return info
    
    def generate_doc_id(self, doc_name: str, company: str) -> str:
        """Generate unique document ID"""
        hash_suffix = hashlib.md5(f"{doc_name}{company}".encode()).hexdigest()[:8]
        return f"{company}_{doc_name}_{hash_suffix}"
    
    def determine_section(self, item: Dict, item_type: str, text: str = "") -> str:
        """Enhanced section detection"""
        # Check object type
        if 'obj_type' in item:
            obj_type = item['obj_type'].lower()
            if 'title' in obj_type:
                return "document_title"
            elif 'section_header' in obj_type:
                return "section_header"
            elif 'caption' in obj_type:
                return "caption"
        
        # SEC-specific sections from text content
        text_lower = text.lower() if text else ""
        if 'risk factor' in text_lower:
            return "risk_factors"
        elif 'management discussion' in text_lower or 'md&a' in text_lower:
            return "md&a"
        elif 'financial statement' in text_lower:
            return "financial_statements"
        elif 'business overview' in text_lower:
            return "business_overview"
        
        # Default by type
        return {
            'table': 'financial_table',
            'picture': 'figure',
            'text': 'body_text'
        }.get(item_type, 'unknown')
    
    def process_document(self, doc_name: str) -> List[Dict]:
        """Process all outputs for a document and create metadata records"""
        print(f"\nProcessing: {doc_name}")
        
        # Load main JSON
        json_path = self.json_dir / f"{doc_name}.json"
        if not json_path.exists():
            print(f"  ✗ JSON file not found: {json_path}")
            return []
        
        with open(json_path, 'r', encoding='utf-8') as f:
            doc_data = json.load(f)
        
        # Load supplementary data
        print("  Loading supplementary data:")
        bbox_data = self.load_bounding_boxes_csv(doc_name)
        print(f"    • Bounding boxes: {len(bbox_data)} items")
        
        layout_data = self.load_layout_json(doc_name)
        print(f"    • Layout JSON: {'✓' if layout_data else '✗'}")
        
        # Extract document metadata
        company_info = self.extract_company_info(doc_name)
        doc_id = self.generate_doc_id(doc_name, company_info['company'])
        
        records = []
        
        # Process text items
        if 'texts' in doc_data:
            print(f"  Processing {len(doc_data['texts'])} text items")
            for idx, text_item in enumerate(doc_data['texts']):
                text_content = text_item.get('text', '')
                
                # Get bbox from CSV or JSON
                bbox_key = f"text_{idx}"
                bbox = bbox_data.get(bbox_key, {})
                
                # Fallback to JSON provenance
                if not bbox and 'prov' in text_item and text_item['prov']:
                    prov = text_item['prov'][0]
                    if 'bbox' in prov:
                        bbox = {
                            "page": prov.get('page_no', 1),
                            "left": prov['bbox'].get('l', 0),
                            "top": prov['bbox'].get('t', 0),
                            "right": prov['bbox'].get('r', 0),
                            "bottom": prov['bbox'].get('b', 0)
                        }
                
                page = bbox.get('page', 1)
                section = self.determine_section(text_item, 'text', text_content)
                
                record = {
                    "doc_id": doc_id,
                    "company": company_info['company'],
                    "fiscal_year": company_info['fiscal_year'],
                    "filing_type": company_info['filing_type'],
                    "page": page,
                    "section": section,
                    "block_type": "text",
                    "bbox": bbox,
                    "text": text_content[:1000],
                    "text_full_length": len(text_content),
                    "source_path": str(json_path),
                    "item_index": idx,
                    "extraction_timestamp": datetime.now().isoformat(),
                    "extraction_method": "docling"
                }
                records.append(record)
        
        # Process tables with actual CSV data
        if 'tables' in doc_data:
            print(f"  Processing {len(doc_data['tables'])} tables")
            for idx, table in enumerate(doc_data['tables']):
                # Load actual table data from CSV
                table_data = self.load_table_csv(doc_name, idx)
                
                # Get bbox
                bbox_key = f"table_{idx}"
                bbox = bbox_data.get(bbox_key, {})
                
                # Fallback to JSON
                if not bbox and 'prov' in table and table['prov']:
                    prov = table['prov'][0]
                    bbox = {
                        "page": prov.get('page_no', 1),
                        "left": prov['bbox'].get('l', 0),
                        "top": prov['bbox'].get('t', 0),
                        "right": prov['bbox'].get('r', 0),
                        "bottom": prov['bbox'].get('b', 0)
                    }
                
                record = {
                    "doc_id": doc_id,
                    "company": company_info['company'],
                    "fiscal_year": company_info['fiscal_year'],
                    "filing_type": company_info['filing_type'],
                    "page": bbox.get('page', 1),
                    "section": "financial_table",
                    "block_type": "table",
                    "bbox": bbox,
                    "text": table_data["preview"] if table_data["exists"] else f"Table {idx + 1}",
                    "text_full_length": table_data["rows"] * table_data["columns"],
                    "source_path": str(self.tables_dir / doc_name / f"table_{idx + 1}.csv"),
                    "table_info": {
                        "rows": table_data["rows"],
                        "columns": table_data["columns"],
                        "csv_exists": table_data["exists"]
                    },
                    "item_index": idx,
                    "extraction_timestamp": datetime.now().isoformat(),
                    "extraction_method": "docling"
                }
                records.append(record)
        
        # Process figures with file existence check
        if 'pictures' in doc_data:
            print(f"  Processing {len(doc_data['pictures'])} figures")
            for idx, picture in enumerate(doc_data['pictures']):
                # Check if PNG exists
                figure_info = self.check_figure_exists(doc_name, idx)
                
                # Get bbox
                bbox_key = f"figure_{idx}"
                bbox = bbox_data.get(bbox_key, {})
                
                # Fallback
                if not bbox and 'prov' in picture and picture['prov']:
                    prov = picture['prov'][0]
                    bbox = {
                        "page": prov.get('page_no', 1),
                        "left": prov['bbox'].get('l', 0),
                        "top": prov['bbox'].get('t', 0),
                        "right": prov['bbox'].get('r', 0),
                        "bottom": prov['bbox'].get('b', 0)
                    }
                
                caption = picture.get('caption', f"Figure {idx + 1}")
                
                record = {
                    "doc_id": doc_id,
                    "company": company_info['company'],
                    "fiscal_year": company_info['fiscal_year'],
                    "filing_type": company_info['filing_type'],
                    "page": bbox.get('page', 1),
                    "section": "figure",
                    "block_type": "picture",
                    "bbox": bbox,
                    "text": caption,
                    "text_full_length": len(caption),
                    "source_path": figure_info["path"] if figure_info["exists"] else str(json_path),
                    "figure_info": {
                        "png_exists": figure_info["exists"],
                        "file_size": figure_info["size"]
                    },
                    "item_index": idx,
                    "extraction_timestamp": datetime.now().isoformat(),
                    "extraction_method": "docling"
                }
                records.append(record)
        
        print(f"  ✓ Created {len(records)} metadata records")
        return records
    
    def save_jsonl(self, records: List[Dict], doc_name: str):
        """Save records as JSONL"""
        jsonl_path = self.metadata_dir / f"{doc_name}.jsonl"
        with open(jsonl_path, 'w', encoding='utf-8') as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(f"  ✓ Saved to: {jsonl_path}")
    
    def create_section_markdown(self, records: List[Dict], doc_name: str):
        """Create section-based markdown summary"""
        if not records:
            return
        
        # Group by section
        sections = {}
        for record in records:
            section = record['section']
            if section not in sections:
                sections[section] = []
            sections[section].append(record)
        
        # Build markdown
        lines = [
            f"# Document: {doc_name}",
            f"**Company**: {records[0]['company']}",
            f"**Fiscal Year**: {records[0]['fiscal_year']}",
            f"**Filing Type**: {records[0]['filing_type']}",
            f"**Total Items**: {len(records)}",
            "",
            "---",
            ""
        ]
        
        for section_name, items in sections.items():
            lines.append(f"## {section_name.replace('_', ' ').title()}")
            lines.append(f"*Count: {len(items)}*\n")
            
            # Group by type
            by_type = {}
            for item in items:
                block_type = item['block_type']
                if block_type not in by_type:
                    by_type[block_type] = []
                by_type[block_type].append(item)
            
            for block_type, type_items in by_type.items():
                if block_type == 'text':
                    for item in type_items[:5]:  # First 5
                        preview = item['text'][:150] + "..." if len(item['text']) > 150 else item['text']
                        lines.append(f"- **Page {item['page']}**: {preview}")
                
                elif block_type == 'table':
                    for item in type_items:
                        info = item.get('table_info', {})
                        lines.append(f"- **Table {item['item_index'] + 1}** (Page {item['page']})")
                        lines.append(f"  - Size: {info.get('rows', '?')} × {info.get('columns', '?')}")
                        lines.append(f"  - CSV: {'✓' if info.get('csv_exists') else '✗'}")
                
                elif block_type == 'picture':
                    for item in type_items:
                        info = item.get('figure_info', {})
                        lines.append(f"- **Figure {item['item_index'] + 1}** (Page {item['page']}): {item['text']}")
                        lines.append(f"  - PNG: {'✓' if info.get('png_exists') else '✗'}")
            
            lines.append("")
        
        # Save markdown
        md_path = self.sections_dir / f"{doc_name}_sections.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"  ✓ Created summary: {md_path}")
    
    def process_all(self):
        """Process all documents"""
        json_files = sorted(self.json_dir.glob("*.json"))
        
        if not json_files:
            print("No JSON files found")
            return
        
        print(f"Found {len(json_files)} documents to process")
        print("=" * 60)
        
        for json_path in json_files:
            doc_name = json_path.stem
            
            # Process document
            records = self.process_document(doc_name)
            
            if records:
                # Save outputs
                self.save_jsonl(records, doc_name)
                self.create_section_markdown(records, doc_name)
        
        print("\n" + "=" * 60)
        print("✓ Metadata extraction complete!")
        print(f"  • JSONL files: {self.metadata_dir}")
        print(f"  • Section summaries: {self.sections_dir}")

if __name__ == "__main__":
    processor = EnhancedDoclingMetadataProcessor()
    processor.process_all()