#!/usr/bin/env python
"""
Part 11 - Step 1: Download Apple's XBRL Files from SEC EDGAR
This script downloads XBRL attachments for Apple's latest 10-K filing
"""

from pathlib import Path
from sec_edgar_downloader import Downloader
import shutil
import sys
import json
from datetime import datetime

def setup_directories():
    """Create necessary directories"""
    dirs = [
        Path("data/xbrl"),
        Path("data/validation"),
        Path("logs")
    ]
    for dir_path in dirs:
        dir_path.mkdir(parents=True, exist_ok=True)
    return dirs[0]  # Return xbrl_dir

def download_apple_xbrl(your_email, your_institution="Northeastern University"):
    """
    Download Apple's XBRL files from SEC EDGAR
    
    Args:
        your_email: Your email address (required by SEC)
        your_institution: Your institution name (required by SEC)
    """
    
    print("="*70)
    print(" Part 11 - Step 1: Download Apple (AAPL) XBRL Files ".center(70))
    print("="*70)
    
    # Setup directories
    xbrl_dir = setup_directories()
    
    print(f"\nConfiguration:")
    print(f"  Company: Apple Inc. (AAPL)")
    print(f"  Filing Type: 10-K (Annual Report)")
    print(f"  Institution: {your_institution}")
    print(f"  Contact Email: {your_email}")
    print("-"*70)
    
    # Initialize SEC EDGAR downloader
    print("\n[1/4] Initializing SEC EDGAR downloader...")
    try:
        dl = Downloader(
            company_name=your_institution,
            email_address=your_email
        )
        print("✓ Downloader initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        return None, []
    
    # Download Apple's 10-K with XBRL
    print("\n[2/4] Downloading Apple's 10-K filing from SEC...")
    print("      (This may take 30-60 seconds)")
    
    try:
        dl.get(
            "10-K",                    # Annual report
            "AAPL",                    # Apple ticker
            limit=1,                   # Most recent filing
            download_details=True,     # Get all attachments including XBRL
            after="2023-01-01",       # Recent filings
            before="2024-12-31"
        )
        print("✓ Download completed")
    except Exception as e:
        print(f"✗ Download failed: {e}")
        print("\nTrying alternative: 10-Q filing...")
        try:
            dl.get("10-Q", "AAPL", limit=1, download_details=True, after="2023-01-01")
            print("✓ Downloaded 10-Q instead")
        except:
            print("✗ Both 10-K and 10-Q downloads failed")
            return None, []
    
    # Process downloaded files
    print("\n[3/4] Processing downloaded files...")
    source_dir = Path("sec-edgar-filings/AAPL")
    
    if not source_dir.exists():
        print(f"✗ No files found at {source_dir}")
        return None, []
    
    xbrl_files = []
    instance_doc = None
    filing_info = {}
    
    # Search for XBRL files in both 10-K and 10-Q directories
    for filing_type in ["10-K", "10-Q"]:
        filing_path = source_dir / filing_type
        if not filing_path.exists():
            continue
            
        print(f"\nSearching in {filing_path}...")
        
        for filing_folder in filing_path.iterdir():
            if not filing_folder.is_dir():
                continue
                
            print(f"  Checking folder: {filing_folder.name}")
            filing_info['folder'] = filing_folder.name
            filing_info['type'] = filing_type
            
            # Look for XBRL files
            xml_files = list(filing_folder.glob("*.xml"))
            xsd_files = list(filing_folder.glob("*.xsd"))
            
            for file in xml_files + xsd_files:
                # Check if it's an XBRL file
                is_xbrl = False
                
                if file.suffix == '.xml':
                    try:
                        content = file.read_text(encoding='utf-8', errors='ignore')[:2000]
                        if any(marker in content.lower() for marker in ['xbrl', 'instance', 'context']):
                            is_xbrl = True
                    except:
                        pass
                elif file.suffix == '.xsd':
                    is_xbrl = True  # Schema files are part of XBRL
                
                if is_xbrl:
                    # Copy to our xbrl directory
                    dest_name = f"AAPL_{filing_type}_{file.name}"
                    dest_path = xbrl_dir / dest_name
                    shutil.copy2(file, dest_path)
                    xbrl_files.append(dest_path)
                    
                    # Check if this is the main instance document
                    if 'aapl-' in file.name.lower() and file.suffix == '.xml':
                        instance_doc = dest_path
                        print(f"    ✓ Main instance: {file.name}")
                    else:
                        print(f"    ✓ Found: {file.name}")
    
    # If no instance doc identified, use first XML
    if not instance_doc and xbrl_files:
        for f in xbrl_files:
            if f.suffix == '.xml':
                instance_doc = f
                break
    
    # Save metadata
    print("\n[4/4] Saving metadata...")
    metadata = {
        "download_date": datetime.now().isoformat(),
        "company": "Apple Inc.",
        "ticker": "AAPL",
        "filing_type": filing_info.get('type', 'unknown'),
        "filing_folder": filing_info.get('folder', 'unknown'),
        "instance_document": str(instance_doc) if instance_doc else None,
        "total_files": len(xbrl_files),
        "files": [str(f) for f in xbrl_files]
    }
    
    metadata_path = xbrl_dir / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Metadata saved to {metadata_path}")
    
    # Summary
    print("\n" + "="*70)
    if xbrl_files:
        print(f"✓ SUCCESS: Downloaded {len(xbrl_files)} XBRL files for Apple")
        print(f"\nDetails:")
        print(f"  - Filing Type: {filing_info.get('type', 'N/A')}")
        print(f"  - Files saved to: data/xbrl/")
        if instance_doc:
            print(f"  - Main document: {instance_doc.name}")
        print(f"\n✓ Ready for Step 2: Parse XBRL")
    else:
        print("✗ No XBRL files found")
        print("\nManual download required:")
        print("  1. Go to: https://www.sec.gov/edgar/search/")
        print("  2. Search for: AAPL")
        print("  3. Download XBRL files from latest 10-K")
        print("  4. Save to: data/xbrl/")
    
    print("="*70)
    
    return instance_doc, xbrl_files

def main():
    """Main function"""
    
    # IMPORTANT: Update these with YOUR information
    YOUR_EMAIL = "desai.tap@northeastern.edu"  
    YOUR_INSTITUTION = "Northeastern University"
    
    # Check if email was updated
    if YOUR_EMAIL == "your.email@northeastern.edu":
        print("\n⚠️  IMPORTANT: Update YOUR_EMAIL in this script!")
        print("   Edit line 196 and replace with your actual email")
        response = input("\nDo you want to continue with default? (y/n): ")
        if response.lower() != 'y':
            print("Please update the email first.")
            sys.exit(1)
    
    # Run download
    instance_doc, files = download_apple_xbrl(YOUR_EMAIL, YOUR_INSTITUTION)
    
    if files:
        print(f"\n✅ Step 1 Complete!")
        print(f"   Downloaded {len(files)} XBRL files")
        print(f"   Next: Run step2_parse_xbrl.py")
    else:
        print(f"\n⚠️  Step 1 requires manual download")
        sys.exit(1)

if __name__ == "__main__":
    main()
