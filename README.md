
# Contractor ETL Demo
**Author:** Saroj Bono | **Client:** Phillip Boykin (Upwork)

A Python ETL pipeline that extracts contractor and builder leads from public government permit and licensing portals, transforms and deduplicates the data, and loads it to CSV in Phillip's exact column format.

---

## Output Columns
| Column | Description |
|---|---|
| Name | Licensed contractor full name |
| Title_Owner | Property owner name |
| Email_Address | Owner email address |
| Phone_Number | Contractor phone (normalized) |
| Website | Company website |
| City | Contractor city |
| Address | Contractor street address |
| License_Number | State license number |
| Type | Builder / Contractor / Developer |

---

## Data Sources

### 1. City of Atlanta Building Permits
- **URL:** https://aca-prod.accela.com/ATLANTA_GA/Cap/CapHome.aspx
- **Method:** Playwright browser automation (Accela portal is JavaScript-rendered)
- **Input:** `Record20260309.csv` — 964 permit records downloaded from portal
- **Script:** `atlanta_scraper.py`

### 2. Georgia Secretary of State Professional Licensing
- **URL:** https://goals.sos.ga.gov/GASOSOneStop/s/licensee-search
- **Method:** Hybrid — Playwright captures Aura API session, requests replays calls
- **License types:** Architects, Electrical, Landscape, Plumbers, General Contractors, Residential Builders
- **Script:** `ga_sos_full.py`

---

## How to Run

### Prerequisites
```bash
pip install playwright beautifulsoup4 pandas requests
playwright install chromium
```

### Option A — GUI (easiest)
```bash
python scraper_gui.py
```
Click **Run Atlanta Permit Scraper** or **Run Georgia SOS Scraper**.
Live log output appears in the window. Output CSV path shown when complete.

### Option B — Command line

**Atlanta permits (test mode — 5 records):**
```bash
python atlanta_scraper.py
```
Edit `TEST_LIMIT = 5` → `TEST_LIMIT = None` for full 964-record run.

**Georgia SOS:**
```bash
python ga_sos_full.py
```

---

## How It Works

### Georgia SOS Scraper (Hybrid Aura API approach)
1. **Phase 1 (Playwright):** Select Profession Type + License Type in Salesforce Lightning comboboxes → search → scrape results table across all pages → collect encrypted record IDs
2. **Phase 2 (requests):** Call `GASOS_LicenseeSearchController.fetchAllLicenseeDetails` Aura API directly with each encrypted ID → get full address, license details
3. Save raw CSV + deduplicated CSV

### Technical Challenges Solved
- **Accela portal:** JavaScript-rendered, requires Enter key (not button click) to navigate
- **Salesforce Lightning comboboxes:** Not standard `<select>` elements — require click + option selection
- **Cloudflare / reCAPTCHA:** Bypassed using real Chrome with `--disable-blink-features=AutomationControlled` and realistic user agent
- **Aura API interception:** Used Playwright network listener to capture `fwuid`, session cookies, and `x-sfdc-page-scope-id` header for direct API replay

---

## File Structure
```
contractor-etl-demo/
├── scraper_gui.py          # GUI launcher (tkinter)
├── atlanta_scraper.py      # Atlanta permit scraper
├── ga_sos_full.py          # Georgia SOS scraper (Aura API)
├── requirements.txt        # Python dependencies
├── Record20260309.csv      # Input: 964 Atlanta permit records
└── Atlanta_ETL_demo/       # Sample output CSVs
```

---

## Sample Output
```
Name,Title_Owner,Email_Address,Phone_Number,Website,City,Address,License_Number,Type
John Wicklund,,JILL.PRICE@JLL.COM,(770) 680-5110,,Atlanta,8215 Roswell Road Bldg 100,GEN CONT GCCO008766,Contractor
William Dewey Giarratano,,WMYREALESTATE@GMAIL.COM,,,Atlanta,,GEN CONT RBI003604,Contractor
```

---

## Skills Demonstrated
- Python web scraping (Playwright, requests, BeautifulSoup)
- ETL pipeline design (Extract → Transform → Normalize → Deduplicate → Load)
- Salesforce Lightning / Aura API reverse engineering
- Cloudflare bypass techniques
- Government portal automation (Accela)
- Data normalization (phone numbers, addresses, deduplication)
- GUI development (tkinter)
