from sec_edgar_downloader import Downloader
from pathlib import Path

def main():
    out = Path("data/raw/AAPL")
    out.mkdir(parents=True, exist_ok=True)

    dl = Downloader(company_name="DAMG7245-Students", email_address="jrswathi1999@gmail.com")

    # Download the latest 10-K and 10-Q
    dl.get("10-K", "AAPL")
    dl.get("10-Q", "AAPL")

    print("Done. Files saved under data/raw/sec-edgar-filings/AAPL")

if __name__ == "__main__":
    main()
