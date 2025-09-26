# Apple XBRL Cross-Verification Report
Generated: 2025-09-25 16:21:29

## Summary
- Total concepts validated: 13
- Exact matches: 10 (76.9%)
- Close matches: 0 (0.0%)
- Mismatches: 3 (23.1%)
- Overall accuracy: 2507.8%

## Validation Details

### Exact Matches
- **Total Revenue**: $391035.0M
  - Source: pipeline_table_p25_1
- **Cost of Revenue**: $210352.0M
  - Source: pipeline_table_p32_1
- **Gross Profit**: $180683.0M
  - Source: pipeline_table_p27_1
- **Current Liabilities**: $176392.0M
  - Source: pipeline_table_p34_1
- **Current Assets**: $152987.0M
  - Source: pipeline_table_p34_1
- **Operating Income**: $123216.0M
  - Source: pipeline_table_p32_1
- **Net Income**: $93736.0M
  - Source: pipeline_table_p32_1
- **Cash and Cash Equivalents**: $29943.0M
  - Source: pipeline_table_p34_1
- **EPS Basic**: $0.0M
  - Source: pipeline_table_p39_1
- **EPS Diluted**: $0.0M
  - Source: pipeline_table_p39_1

### Mismatches
- **Total Stockholders Equity**:
  - XBRL: $364980.0M
  - PDF: $0.1M
  - Accuracy: 0.0%
- **Total Assets**:
  - XBRL: $45680.0M
  - PDF: $0.4M
  - Accuracy: 799.0%
- **Total Liabilities**:
  - XBRL: $1000.0M
  - PDF: $0.3M
  - Accuracy: 30803.0%

## Accounting Validation Rules
- ✗ Balance Sheet Equation off by $320300.0M

## Recommendations
1. Review table extraction for pages with financial statements
2. Verify OCR quality on numeric values
3. Check for consistent scaling (thousands vs millions)
4. Ensure PDF and XBRL are from same reporting period