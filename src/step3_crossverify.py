#!/usr/bin/env python
"""
Part 11 - Step 3: Cross-Verification of XBRL vs PDF Tables
Validates extracted PDF table values against official XBRL data
"""

from pathlib import Path
import pandas as pd
import numpy as np
import json
import re
from datetime import datetime
import sys 
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class AppleXBRLValidator:
    """Cross-verify Apple's XBRL data with extracted PDF tables"""
    
    def __init__(self):
        # Mapping: XBRL concepts to possible PDF table labels
        # Customized for Apple's financial statements
        self.concept_mappings = {
            'Total Revenue': [
                'total net sales', 'net sales', 'revenue', 'total revenue',
                'products and services net sales', 'total net revenue'
            ],
            'Cost of Revenue': [
                'cost of sales', 'total cost of sales', 'cost of revenue',
                'cost of goods sold', 'cogs'
            ],
            'Gross Profit': [
                'gross profit', 'gross margin', 'total gross profit',
                'gross profit margin'
            ],
            'Operating Income': [
                'operating income', 'income from operations', 
                'operating profit', 'operating income loss'
            ],
            'Net Income': [
                'net income', 'net earnings', 'net income loss',
                'net profit', 'income net of taxes'
            ],
            'Total Assets': [
                'total assets', 'assets total', 'total consolidated assets'
            ],
            'Current Assets': [
                'total current assets', 'current assets', 'current assets total'
            ],
            'Cash and Cash Equivalents': [
                'cash and cash equivalents', 'cash', 'cash equivalents',
                'cash and equivalents'
            ],
            'Total Liabilities': [
                'total liabilities', 'liabilities total', 
                'total consolidated liabilities'
            ],
            'Current Liabilities': [
                'total current liabilities', 'current liabilities',
                'current liabilities total'
            ],
            'Total Stockholders Equity': [
                'total shareholders equity', 'stockholders equity',
                'shareholders equity', 'total equity', 'equity'
            ],
            'EPS Basic': [
                'earnings per share basic', 'basic earnings per share',
                'eps basic', 'basic eps'
            ],
            'EPS Diluted': [
                'earnings per share diluted', 'diluted earnings per share',
                'eps diluted', 'diluted eps'
            ]
        }
        
        self.validation_results = []
        self.investigation_notes = []
    
    def normalize_text(self, text):
        """Normalize text for comparison"""
        if pd.isna(text):
            return ""
        text = str(text).lower()
        # Remove special characters and extra spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        text = ' '.join(text.split())
        return text
    
    def extract_number(self, value):
        """Extract numeric value from various formats"""
        if pd.isna(value):
            return None
        
        try:
            val_str = str(value)
            # Remove currency symbols and commas
            val_str = re.sub(r'[$,]', '', val_str)
            # Handle parentheses (negative numbers)
            if '(' in val_str and ')' in val_str:
                val_str = '-' + val_str.replace('(', '').replace(')', '')
            # Remove non-numeric characters
            val_str = re.sub(r'[^\d.-]', '', val_str)
            
            if val_str and val_str not in ['-', '.', '-.']:
                return float(val_str)
        except:
            pass
        return None
    
    def find_in_table(self, table_df, search_labels):
        """Find value in table matching search labels"""
        
        for label in search_labels:
            normalized_label = self.normalize_text(label)
            
            # Search first column (labels)
            for idx, row in table_df.iterrows():
                if len(row) < 2:
                    continue
                
                first_col = self.normalize_text(row.iloc[0])
                
                # Check for match
                if normalized_label in first_col or (
                    len(normalized_label) > 5 and normalized_label in first_col
                ):
                    # Found match, extract value from subsequent columns
                    for col_idx in range(1, min(len(row), 5)):  # Check first few value columns
                        value = self.extract_number(row.iloc[col_idx])
                        if value is not None and abs(value) > 0.01:  # Ignore near-zero values
                            return {
                                'value': value,
                                'label': str(row.iloc[0]),
                                'row': idx,
                                'column': col_idx,
                                'table_shape': table_df.shape
                            }
        return None
    
    def load_xbrl_data(self):
        """Load parsed XBRL data from Step 2"""
        csv_path = Path("data/validation/xbrl_financial_data.csv")
        json_path = Path("data/validation/xbrl_financial_data.json")
        
        if not csv_path.exists():
            print("✗ XBRL data not found. Run step2_parse_xbrl.py first")
            return None, None
        
        df = pd.read_csv(csv_path)
        
        with open(json_path, 'r') as f:
            json_data = json.load(f)
        
        print(f"✓ Loaded {len(df)} XBRL financial items")
        
        return df, json_data
    
    def load_pdf_tables(self):
        """Load extracted PDF tables"""
        tables = {}
        
        # Load from traditional pipeline
        pipeline_dir = Path("data/parsed/Apple_SEA/tables")
        if pipeline_dir.exists():
            print(f"\nLoading pipeline tables from: {pipeline_dir}")
            for csv_file in sorted(pipeline_dir.glob("*.csv")):
                try:
                    df = pd.read_csv(csv_file)
                    if not df.empty:
                        tables[f"pipeline_{csv_file.stem}"] = df
                        print(f"  ✓ {csv_file.stem}: {df.shape}")
                except Exception as e:
                    print(f"  ✗ Failed to load {csv_file.stem}: {e}")
        
        # Load from Docling
        docling_dir = Path("data/parsed/docling/tables/Apple_SEA")
        if docling_dir.exists():
            print(f"\nLoading Docling tables from: {docling_dir}")
            for csv_file in sorted(docling_dir.glob("*.csv")):
                try:
                    df = pd.read_csv(csv_file)
                    if not df.empty:
                        tables[f"docling_{csv_file.stem}"] = df
                        print(f"  ✓ {csv_file.stem}: {df.shape}")
                except Exception as e:
                    print(f"  ✗ Failed to load {csv_file.stem}: {e}")
        
        print(f"\n✓ Loaded {len(tables)} PDF tables total")
        return tables
    
    def validate(self, xbrl_df, pdf_tables):
        """Main validation function"""
        
        print("\n" + "-"*50)
        print("Cross-Verification Results:")
        print("-"*50)
        
        for _, xbrl_row in xbrl_df.iterrows():
            concept = xbrl_row['concept']
            xbrl_value = xbrl_row['value']
            
            # Get search labels for this concept
            search_labels = self.concept_mappings.get(concept, [concept.lower()])
            
            # Search in each PDF table
            matches_found = []
            
            for table_name, table_df in pdf_tables.items():
                result = self.find_in_table(table_df, search_labels)
                
                if result:
                    pdf_value = result['value']
                    
                    # Calculate accuracy with unit scaling detection
                    if abs(xbrl_value) < 0.001 and abs(pdf_value) < 0.001:
                        accuracy = 100.0
                        diff_pct = 0.0
                    elif abs(xbrl_value) < 0.001:
                        accuracy = 0.0
                        diff_pct = 100.0
                    else:
                        ratio = pdf_value / xbrl_value
                        
                        # Check for common scaling factors
                        if 0.000001 <= abs(ratio) <= 0.01:  # PDF in millions, XBRL in full dollars
                            normalized_pdf = pdf_value * 1e6  # Convert PDF to full dollars
                            accuracy = (normalized_pdf / xbrl_value) * 100
                        elif 100 <= abs(ratio) <= 1000000:  # XBRL in millions, PDF in full dollars  
                            normalized_xbrl = xbrl_value * 1e6  # Convert XBRL to full dollars
                            accuracy = (pdf_value / normalized_xbrl) * 100
                        else:
                            accuracy = (pdf_value / xbrl_value) * 100
                        
                        diff_pct = abs(100 - accuracy)
                    
                    # Determine match quality
                    if diff_pct < 0.1:
                        quality = "EXACT"
                        symbol = "✓"
                    elif diff_pct < 5:
                        quality = "CLOSE"
                        symbol = "≈"
                    else:
                        quality = "MISMATCH"
                        symbol = "✗"
                    
                    matches_found.append({
                        'concept': concept,
                        'xbrl_value': xbrl_value,
                        'pdf_value': pdf_value,
                        'pdf_source': table_name,
                        'pdf_label': result['label'],
                        'accuracy': accuracy,
                        'difference_pct': diff_pct,
                        'match_quality': quality,
                        'symbol': symbol
                    })
            
            # Report best match
            if matches_found:
                # Sort by accuracy
                matches_found.sort(key=lambda x: abs(100 - x['accuracy']))
                best_match = matches_found[0]
                
                self.validation_results.append(best_match)
                
                # Format values for display
                xbrl_fmt = f"${best_match['xbrl_value']/1e6:.1f}M" if abs(best_match['xbrl_value']) >= 1e6 else f"${best_match['xbrl_value']:.2f}"
                pdf_fmt = f"${best_match['pdf_value']/1e6:.1f}M" if abs(best_match['pdf_value']) >= 1e6 else f"${best_match['pdf_value']:.2f}"
                
                print(f"{best_match['symbol']} {concept:.<30} XBRL: {xbrl_fmt:.>12} | PDF: {pdf_fmt:.>12} | Acc: {best_match['accuracy']:.1f}%")
                
                # Investigate mismatches
                if best_match['match_quality'] == "MISMATCH":
                    self.investigate_mismatch(best_match)
    
    def investigate_mismatch(self, match):
        """Investigate cause of mismatch"""
        causes = []
        
        ratio = match['pdf_value'] / match['xbrl_value'] if match['xbrl_value'] != 0 else 0
        
        # Check for scaling issues
        if abs(ratio - 1000) < 10:
            causes.append("Scaling: PDF in thousands, XBRL in millions")
        elif abs(ratio - 0.001) < 0.0001:
            causes.append("Scaling: PDF in millions, XBRL in thousands")
        
        # Check for sign difference
        if abs(match['pdf_value'] + match['xbrl_value']) < abs(match['xbrl_value'] * 0.1):
            causes.append("Sign difference (positive vs negative)")
        
        # Check for OCR issues (close but not exact)
        if 80 < match['accuracy'] < 120:
            causes.append("Likely OCR error in digit recognition")
        
        # Check for period mismatch
        if match['pdf_source'] and 'quarter' in match['pdf_source'].lower():
            causes.append("Possible period mismatch (quarterly vs annual)")
        
        if causes:
            self.investigation_notes.append({
                'concept': match['concept'],
                'causes': causes
            })
    
    def apply_validation_rules(self, results_df):
        """Apply accounting validation rules"""
        rules_passed = []
        
        # Balance Sheet Equation
        assets = results_df[results_df['concept'] == 'Total Assets']['xbrl_value'].iloc[0] if 'Total Assets' in results_df['concept'].values else None
        liabilities = results_df[results_df['concept'] == 'Total Liabilities']['xbrl_value'].iloc[0] if 'Total Liabilities' in results_df['concept'].values else None
        equity = results_df[results_df['concept'] == 'Total Stockholders Equity']['xbrl_value'].iloc[0] if 'Total Stockholders Equity' in results_df['concept'].values else None
        
        if all(v is not None for v in [assets, liabilities, equity]):
            expected = liabilities + equity
            diff = abs(assets - expected)
            tolerance = assets * 0.01  # 1% tolerance
            
            if diff <= tolerance:
                rules_passed.append("✓ Balance Sheet Equation: Assets = Liabilities + Equity")
            else:
                rules_passed.append(f"✗ Balance Sheet Equation off by ${diff/1e6:.1f}M")
        
        return rules_passed

def generate_report(validation_results, investigation_notes, validation_rules):
    """Generate final validation report"""
    
    report = []
    report.append("# Apple XBRL Cross-Verification Report")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # Summary statistics
    df = pd.DataFrame(validation_results) if validation_results else pd.DataFrame()
    
    if not df.empty:
        exact = len(df[df['match_quality'] == 'EXACT'])
        close = len(df[df['match_quality'] == 'CLOSE'])
        mismatch = len(df[df['match_quality'] == 'MISMATCH'])
        
        report.append("## Summary")
        report.append(f"- Total concepts validated: {len(df)}")
        report.append(f"- Exact matches: {exact} ({exact/len(df)*100:.1f}%)")
        report.append(f"- Close matches: {close} ({close/len(df)*100:.1f}%)")
        report.append(f"- Mismatches: {mismatch} ({mismatch/len(df)*100:.1f}%)")
        report.append(f"- Overall accuracy: {df['accuracy'].mean():.1f}%")
        report.append("")
        
        # Detailed results by category
        report.append("## Validation Details")
        
        # Exact matches
        exact_df = df[df['match_quality'] == 'EXACT']
        if not exact_df.empty:
            report.append("\n### Exact Matches")
            for _, row in exact_df.iterrows():
                report.append(f"- **{row['concept']}**: ${row['xbrl_value']/1e6:.1f}M")
                report.append(f"  - Source: {row['pdf_source']}")
        
        # Close matches
        close_df = df[df['match_quality'] == 'CLOSE']
        if not close_df.empty:
            report.append("\n### Close Matches")
            for _, row in close_df.iterrows():
                report.append(f"- **{row['concept']}**:")
                report.append(f"  - XBRL: ${row['xbrl_value']/1e6:.1f}M")
                report.append(f"  - PDF: ${row['pdf_value']/1e6:.1f}M")
                report.append(f"  - Accuracy: {row['accuracy']:.1f}%")
        
        # Mismatches
        mismatch_df = df[df['match_quality'] == 'MISMATCH']
        if not mismatch_df.empty:
            report.append("\n### Mismatches")
            for _, row in mismatch_df.iterrows():
                report.append(f"- **{row['concept']}**:")
                report.append(f"  - XBRL: ${row['xbrl_value']/1e6:.1f}M")
                report.append(f"  - PDF: ${row['pdf_value']/1e6:.1f}M")
                report.append(f"  - Accuracy: {row['accuracy']:.1f}%")
    
    # Investigation notes
    if investigation_notes:
        report.append("\n## Mismatch Analysis")
        for note in investigation_notes:
            report.append(f"- **{note['concept']}**:")
            for cause in note['causes']:
                report.append(f"  - {cause}")
    
    # Validation rules
    if validation_rules:
        report.append("\n## Accounting Validation Rules")
        for rule in validation_rules:
            report.append(f"- {rule}")
    
    report.append("\n## Recommendations")
    report.append("1. Review table extraction for pages with financial statements")
    report.append("2. Verify OCR quality on numeric values")
    report.append("3. Check for consistent scaling (thousands vs millions)")
    report.append("4. Ensure PDF and XBRL are from same reporting period")
    
    return "\n".join(report)

def main():
    """Main function"""
    
    print("="*70)
    print(" Part 11 - Step 3: Cross-Verification ".center(70))
    print("="*70)
    
    # Initialize validator
    validator = AppleXBRLValidator()
    
    # Load XBRL data
    print("\n[1/5] Loading XBRL data...")
    xbrl_df, xbrl_json = validator.load_xbrl_data()
    
    if xbrl_df is None:
        sys.exit(1)
    
    # Load PDF tables
    print("\n[2/5] Loading PDF tables...")
    pdf_tables = validator.load_pdf_tables()
    
    if not pdf_tables:
        print("✗ No PDF tables found")
        sys.exit(1)
    
    # Perform validation
    print("\n[3/5] Cross-verifying values...")
    validator.validate(xbrl_df, pdf_tables)
    
    # Apply validation rules
    print("\n[4/5] Applying validation rules...")
    results_df = pd.DataFrame(validator.validation_results) if validator.validation_results else pd.DataFrame()
    
    validation_rules = []
    if not results_df.empty:
        validation_rules = validator.apply_validation_rules(results_df)
    
    # Generate report
    print("\n[5/5] Generating report...")
    report = generate_report(
        validator.validation_results,
        validator.investigation_notes,
        validation_rules
    )
    
    # Save outputs
    output_dir = Path("data/validation")
    
    if not results_df.empty:
        # Save validation results
        results_path = output_dir / "xbrl_validation_results.csv"
        results_df.to_csv(results_path, index=False)
        print(f"\n✓ Saved results to: {results_path}")
    
    # Save report
    report_path = output_dir / "xbrl_validation_report.md"
    with open(report_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(report)
    print(f"✓ Saved report to: {report_path}")
    
    # Print summary
    print("\n" + "="*70)
    print("VALIDATION COMPLETE")
    print("="*70)
    
    if not results_df.empty:
        print(f"\nResults Summary:")
        print(f"  - Concepts validated: {len(results_df)}")
        print(f"  - Average accuracy: {results_df['accuracy'].mean():.1f}%")
        print(f"  - Exact matches: {len(results_df[results_df['match_quality'] == 'EXACT'])}")
        
        print(f"\n✅ Step 3 Complete!")
        print(f"   Check data/validation/ for detailed reports")
    else:
        print("\n⚠ No validations performed - check your data")
    
    print("="*70)

if __name__ == "__main__":
    main()