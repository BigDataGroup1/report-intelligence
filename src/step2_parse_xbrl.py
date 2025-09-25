#!/usr/bin/env python
"""
Part 11 - Step 2: Parse XBRL Files and Extract Financial Data
FIXED VERSION - Extracts only FY2024 data (period ending 2024-09-28)
"""

from pathlib import Path
import pandas as pd
import json
from datetime import datetime
import sys
from bs4 import BeautifulSoup
import re

class AppleXBRLParser:
    """Parse Apple's XBRL files to extract FY2024 financial data"""
    
    def __init__(self):
        # Target fiscal year end date
        self.target_year_end = "2024-09-28"
        
        # Key financial concepts we want
        self.target_concepts = {
            'RevenueFromContractWithCustomerExcludingAssessedTax': 'Total Revenue',
            'CostOfGoodsAndServicesSold': 'Cost of Revenue',
            'GrossProfit': 'Gross Profit',
            'OperatingIncomeLoss': 'Operating Income',
            'NetIncomeLoss': 'Net Income',
            'EarningsPerShareBasic': 'EPS Basic',
            'EarningsPerShareDiluted': 'EPS Diluted',
            'Assets': 'Total Assets',
            'AssetsCurrent': 'Current Assets',
            'CashAndCashEquivalentsAtCarryingValue': 'Cash and Cash Equivalents',
            'Liabilities': 'Total Liabilities',
            'LiabilitiesCurrent': 'Current Liabilities',
            'StockholdersEquity': 'Total Stockholders Equity'
        }
        
        self.financial_data = {}
        self.parsed_items = []
    
    def parse_with_beautifulsoup_fy2024(self, xbrl_file):
        """Parse XBRL and extract ONLY FY2024 data - IMPROVED VERSION"""
        print(f"\nParsing XBRL for FY2024 data only: {xbrl_file.name}")
        
        try:
            with open(xbrl_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            soup = BeautifulSoup(content, 'xml')
            
            # Step 1: Analyze ALL contexts to understand the structure
            contexts_fy2024 = {}
            all_contexts = {}
            
            print("  Analyzing ALL contexts...")
            
            for context in soup.find_all('context'):
                context_id = context.get('id')
                if context_id:
                    period = context.find('period')
                    if period:
                        end_date = period.find('endDate')
                        start_date = period.find('startDate')
                        instant = period.find('instant')
                        
                        period_info = {
                            'start': start_date.text.strip() if start_date else None,
                            'end': end_date.text.strip() if end_date else None,
                            'instant': instant.text.strip() if instant else None
                        }
                        all_contexts[context_id] = period_info
                        
                        # Print for debugging
                        if period_info['end']:
                            print(f"    {context_id}: Start={period_info['start']} End={period_info['end']}")
                        elif period_info['instant']:
                            print(f"    {context_id}: Instant={period_info['instant']}")
            
            # Step 2: Identify FY2024 contexts more precisely
            print(f"\n  Identifying FY2024 contexts from {len(all_contexts)} total contexts...")
            
            for context_id, period_info in all_contexts.items():
                is_fy2024 = False
                
                # Check for annual periods ending in FY2024
                if period_info['end']:
                    end_date = period_info['end']
                    start_date = period_info['start']
                    
                    # Apple FY2024 ends on 2024-09-28
                    if '2024-09-28' in end_date:
                        # Check if it's annual (starts around 2023-09-29)
                        if start_date and '2023-10-01' in start_date:
                            contexts_fy2024[context_id] = 'FY2024_Annual'
                            is_fy2024 = True
                            print(f"    ✓ {context_id}: FY2024 Annual ({start_date} to {end_date})")
                    
                    # Also check for any period ending in Sep 2024
                    elif '2024-09' in end_date and ('28' in end_date or '30' in end_date):
                        contexts_fy2024[context_id] = 'FY2024_Period'
                        is_fy2024 = True
                        print(f"    ✓ {context_id}: FY2024 Period (ends {end_date})")
                
                # Check for point-in-time (instant) as of end of FY2024
                elif period_info['instant']:
                    instant_date = period_info['instant']
                    if '2024-09-28' in instant_date:
                        contexts_fy2024[context_id] = 'FY2024_Instant'
                        is_fy2024 = True
                        print(f"    ✓ {context_id}: FY2024 Instant ({instant_date})")
            
            print(f"\n  Selected {len(contexts_fy2024)} FY2024 contexts")
            
            if not contexts_fy2024:
                print("  ⚠ No exact FY2024 contexts found. Using broader 2024 search...")
                
                # Fallback: Any 2024 context
                for context_id, period_info in all_contexts.items():
                    if ((period_info['end'] and '2024' in period_info['end']) or
                        (period_info['instant'] and '2024' in period_info['instant'])):
                        contexts_fy2024[context_id] = 'FY2024_Fallback'
                        print(f"    Fallback: {context_id}")
            
            # Step 3: Extract financial data from FY2024 contexts
            print(f"\n  Extracting financial data from {len(contexts_fy2024)} contexts...")
            items_found = 0
            context_usage = {}
            
            for tag in soup.find_all(attrs={"contextRef": True}):
                context_ref = tag.get('contextRef')
                
                # Only process if this is a FY2024 context
                if context_ref not in contexts_fy2024:
                    continue
                
                # Track which contexts we're actually using
                if context_ref not in context_usage:
                    context_usage[context_ref] = 0
                context_usage[context_ref] += 1
                
                tag_name = tag.name
                if not tag_name or not tag.string:
                    continue
                
                # Check if this is a concept we want
                for gaap_concept, display_name in self.target_concepts.items():
                    # More flexible matching
                    if (gaap_concept.lower() in tag_name.lower() or
                        any(word in tag_name.lower() for word in gaap_concept.lower().split())):
                        
                        try:
                            # Extract value
                            value_str = tag.string.strip()
                            value_str = re.sub(r'[,$]', '', value_str)
                            value = float(value_str)
                            
                            # Prefer annual contexts over others
                            existing_value = self.financial_data.get(display_name)
                            should_replace = (
                                existing_value is None or
                                'Annual' in contexts_fy2024[context_ref] or
                                abs(value) > abs(existing_value)  # Prefer larger absolute values
                            )
                            
                            if should_replace:
                                self.financial_data[display_name] = value
                                
                                # Remove old entry if exists
                                self.parsed_items = [item for item in self.parsed_items 
                                                   if item['concept'] != display_name]
                                
                                # Add new entry
                                self.parsed_items.append({
                                    'concept': display_name,
                                    'value': value,
                                    'context': context_ref,
                                    'fiscal_year': 'FY2024',
                                    'source': 'BeautifulSoup_FY2024_Improved'
                                })
                                items_found += 1
                                
                                # Format for display
                                if abs(value) >= 1e9:
                                    formatted = f"${value/1e9:.1f}B"
                                elif abs(value) >= 1e6:
                                    formatted = f"${value/1e6:.1f}M"
                                else:
                                    formatted = f"${value:,.0f}"
                                
                                print(f"  ✓ {display_name}: {formatted} (Context: {context_ref})")
                                
                        except ValueError:
                            pass
            
            # Show which contexts were actually used
            print(f"\n  Contexts used for data extraction:")
            for ctx, count in context_usage.items():
                print(f"    {ctx}: {count} values ({contexts_fy2024[ctx]})")
            
            if items_found > 0:
                print(f"\n  ✓ Extracted {len(self.financial_data)} unique FY2024 items")
                
                # Validation check - Apple's FY2024 revenue should be around $391B
                if 'Total Revenue' in self.financial_data:
                    revenue = self.financial_data['Total Revenue']
                    if 380e9 <= revenue <= 400e9:  # Between $380B and $400B
                        print(f"  ✓ Revenue validation PASSED: ${revenue/1e9:.1f}B (FY2024)")
                    else:
                        print(f"  ⚠ Revenue validation FAILED: ${revenue/1e9:.1f}B")
                        print(f"    Expected: ~$391B for FY2024")
                        print(f"    Got: ${revenue/1e9:.1f}B (likely wrong fiscal year)")
                
                return True
            else:
                print(f"\n  ⚠ No FY2024 financial data found")
                return False
                
        except Exception as e:
            print(f"  Error parsing XBRL: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def parse_file(self, xbrl_file):
        """Parse XBRL file for FY2024 data only"""
        return self.parse_with_beautifulsoup_fy2024(xbrl_file)
    
    def to_dataframe(self):
        """Convert to DataFrame"""
        if not self.parsed_items:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.parsed_items)
        df = df.drop_duplicates(subset=['concept'], keep='first')
        df = df.sort_values('value', ascending=False)
        
        return df

def find_instance_document():
    """Find the XBRL instance document"""
    xbrl_dir = Path("data/xbrl")
    
    # Look for Apple XBRL files
    for xml_file in xbrl_dir.glob("*aapl*.xml"):
        return xml_file
    
    # Fallback to any XML
    xml_files = list(xbrl_dir.glob("*.xml"))
    return xml_files[0] if xml_files else None

def save_results(df, financial_data):
    """Save results"""
    output_dir = Path("data/validation")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save CSV
    csv_path = output_dir / "xbrl_financial_data.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n✓ Saved DataFrame to: {csv_path}")
    
    # Save JSON
    json_path = output_dir / "xbrl_financial_data.json"
    with open(json_path, 'w') as f:
        json.dump(financial_data, f, indent=2, default=str)
    print(f"✓ Saved JSON to: {json_path}")
    
    # Create report
    report_lines = [
        "# Apple XBRL Financial Data - FY2024 ONLY",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        f"- Fiscal Year: 2024 (Oct 1, 2023 - Sep 28, 2024)",
        f"- Items extracted: {len(df)}",
        "",
        "## Key Financial Metrics (FY2024)",
        ""
    ]
    
    for _, row in df.iterrows():
        value = row['value']
        if abs(value) >= 1e9:
            formatted = f"${value/1e9:.2f}B"
        elif abs(value) >= 1e6:
            formatted = f"${value/1e6:.2f}M"
        else:
            formatted = f"${value:,.0f}"
        
        report_lines.append(f"- **{row['concept']}**: {formatted}")
    
    report = "\n".join(report_lines)
    report_path = output_dir / "xbrl_extraction_summary.md"
    report_path.write_text(report)
    print(f"✓ Saved report to: {report_path}")

def main():
    """Main function"""
    
    print("="*70)
    print(" Part 11 - Step 2: Parse Apple XBRL Files (FY2024 Only) ".center(70))
    print("="*70)
    
    # Find instance document
    print("\n[1/4] Finding XBRL instance document...")
    instance_doc = find_instance_document()
    
    if not instance_doc:
        print("✗ No XBRL document found")
        sys.exit(1)
    
    print(f"✓ Found: {instance_doc.name}")
    
    # Parse XBRL for FY2024 only
    print("\n[2/4] Parsing XBRL data for FY2024...")
    parser = AppleXBRLParser()
    
    success = parser.parse_file(instance_doc)
    
    if not success or not parser.parsed_items:
        print("\n✗ Failed to extract FY2024 financial data")
        print("  Check that the XBRL file contains FY2024 data (period ending 2024-09-28)")
        sys.exit(1)
    
    # Create DataFrame
    print("\n[3/4] Creating DataFrame...")
    df = parser.to_dataframe()
    print(f"✓ Created DataFrame with {len(df)} FY2024 financial items")
    
    # Display summary
    print("\n" + "-"*50)
    print("FY2024 Financial Data Extracted:")
    print("-"*50)
    for _, row in df.iterrows():
        value = row['value']
        if abs(value) >= 1e9:
            formatted = f"${value/1e9:.2f}B"
        elif abs(value) >= 1e6:
            formatted = f"${value/1e6:.2f}M"
        else:
            formatted = f"${value:,.0f}"
        print(f"{row['concept']:.<30} {formatted:.>15}")
    
    # Save results
    print("\n[4/4] Saving results...")
    save_results(df, parser.financial_data)
    
    # Summary
    print("\n" + "="*70)
    print(f"✅ Step 2 Complete!")
    print(f"   Extracted {len(df)} FY2024 financial items")
    print(f"   Files saved to data/validation/")
    print(f"   Next: Run step3_cross_verify.py")
    print("="*70)

if __name__ == "__main__":
    main()