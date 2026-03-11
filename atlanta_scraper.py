"""
============================================================
 ATLANTA BUILDING PERMIT - CONTRACTOR LEAD SCRAPER v5
 Author : Saroj Bono
 Client : Phillip Boykin (Upwork)

 OUTPUT COLUMNS match Phillip's job description exactly:
   Name, Title_Owner, Email_Address, Phone_Number, Website,
   City, Address, License_Number, Type

 HOW TO RUN:
   python atlanta_scraper.py

 TEST MODE  : TEST_LIMIT = 5    (first 5 records only)
 FULL RUN   : TEST_LIMIT = None (all 964 records ~30 min)

 OUTPUT:
   C:/Users/bonos/Downloads/atlanta_contractor_leads.csv
============================================================
"""

import csv
import time
import re
import pandas as pd
from playwright.sync_api import sync_playwright

# ── CONFIGURATION ─────────────────────────────────────────
INPUT_CSV  = "C:/Users/bonos/Downloads/Record20260309.csv"
OUTPUT_CSV = "C:/Users/bonos/Downloads/atlanta_contractor_leads.csv"

SEARCH_URL   = "https://aca-prod.accela.com/ATLANTA_GA/Cap/CapHome.aspx?module=Building&TabName=Building"
SEARCH_INPUT = '#ctl00_PlaceHolderMain_generalSearchForm_txtGSPermitNumber'

DELAY      = 2.0
TEST_LIMIT = None # ← Change to None for full run of all 964 records


# ── HELPER: NORMALIZE PHONE ───────────────────────────────
def normalize_phone(phone: str) -> str:
    """Convert any phone format to (XXX) XXX-XXXX."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone.strip()


# ── HELPER: DERIVE TYPE ───────────────────────────────────
def derive_type(license_type: str) -> str:
    """
    Map license string to Phillip's required Type values:
    Builder / Contractor / Developer
    """
    lt = license_type.upper()
    if any(x in lt for x in ['BLDR', 'BUILDER', 'RESIDENTIAL', 'RES BASIC']):
        return 'Builder'
    elif any(x in lt for x in ['DEV', 'DEVELOPER', 'LAND DEV']):
        return 'Developer'
    else:
        # GEN CONT, ELEC, PLMR, HVAC, FRAM, ARCH, POOL etc
        return 'Contractor'


# ── PHASE 1: LOAD RECORD NUMBERS ─────────────────────────
def load_record_numbers(csv_path: str, limit=None) -> list:
    """Read the downloaded CSV and return list of permit records."""
    records = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = {
                'record_number': row.get('Record Number', '').strip(),
                'record_type':   row.get('Record Type', '').strip(),
                'date':          row.get('Date', '').strip(),
                'status':        row.get('Status', '').strip(),
                'project_name':  row.get('Project Name', '').strip(),
            }
            if rec['record_number']:
                records.append(rec)
            if limit and len(records) >= limit:
                break
    print(f"Loaded {len(records)} record numbers from CSV")
    return records


# ── PHASE 2: SCRAPE EACH RECORD ───────────────────────────
def scrape_record(page, record: dict) -> dict:
    """
    1. Go to Atlanta permit search page
    2. Type record number and press Enter
    3. Accela redirects to the detail page automatically
    4. Parse Licensed Professional + Owner sections line by line
    5. Return dict with Phillip's exact column names
    """
    record_num = record['record_number']

    # Empty result template — Phillip's exact column names
    empty = {
        'Name':           '',   # Licensed contractor full name
        'Title_Owner':    '',   # Property owner name
        'Email_Address':  '',   # Owner email address
        'Phone_Number':   '',   # Contractor phone number
        'Website':        '',   # Not available on permit pages
        'City':           '',   # Contractor city
        'Address':        '',   # Contractor street address
        'License_Number': '',   # e.g. GEN CONT GCCO008766
        'Type':           '',   # Builder / Contractor / Developer
        # Extra context columns
        'Company_Name':   '',
        'State':          '',
        'Zip':            '',
        'Owner_Address':  '',
        'Owner_City_State': '',
        'Record_Number':  record_num,
        'Record_Type':    record['record_type'],
        'Permit_Date':    record['date'],
        'Permit_Status':  record['status'],
    }

    try:
        # ── NAVIGATE AND SEARCH ───────────────────────────
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        page.fill(SEARCH_INPUT, record_num)
        time.sleep(0.5)
        page.press(SEARCH_INPUT, 'Enter')
        time.sleep(4)

        # ── GET PAGE LINES ────────────────────────────────
        page_text = page.inner_text("body")
        lines = [l.replace('\xa0', ' ').strip() for l in page_text.split("\n") if l.strip()]
        page_joined = " ".join(lines)

        # ── VERIFY WE LANDED ON A DETAIL PAGE ────────────
        on_detail = (
            record_num in page_joined or
            "Licensed Professional:" in page_joined or
            "Record Details" in page_joined
        )
        if not on_detail:
            print(f"  Skipping {record_num} — no detail page found (may have no contractor)")
            return empty

        # ── PARSE LINE BY LINE ────────────────────────────
        current_section  = None
        prev_line        = ""
        prof_data        = {}
        owner_data       = {}
        prof_line_count  = 0
        owner_line_count = 0

        for line in lines:

            # Section boundary detection
            if line == "Licensed Professional:":
                current_section = "professional"
                prof_line_count = 0
                prev_line = line
                continue

            elif line == "Owner:":
                current_section = "owner"
                owner_line_count = 0
                prev_line = line
                continue

            elif line in ["Project Description:", "More Details",
                          "Record Info", "Payments", "Custom Component",
                          "Work Location", "Processing Status"]:
                current_section = None
                prev_line = line
                continue

            # ── PROFESSIONAL SECTION ──────────────────────
            if current_section == "professional":
                prof_line_count += 1

                if prof_line_count == 1:
                    prof_data['name'] = line

                elif prof_line_count == 2:
                    prof_data['company'] = line

                elif prof_line_count == 3:
                    # State license number e.g. 25-112536
                    prof_data['state_lic'] = line

                elif prof_line_count == 4:
                    # Street address
                    prof_data['address'] = line

                elif prof_line_count == 5:
                    # City, State, Zip e.g. "Atlanta, GA, 30350"
                    prof_data['city_line'] = line

                elif line == "Home Phone:":
                    # Phone value is on the NEXT line
                    prev_line = "Home Phone:"
                    continue

                elif line == "Mobile Phone:":
                    prev_line = "Mobile Phone:"
                    continue

                elif prev_line == "Home Phone:":
                    # This line IS the phone number
                    prof_data['phone'] = normalize_phone(line)

                elif prev_line == "Mobile Phone:" and 'phone' not in prof_data:
                    prof_data['phone'] = normalize_phone(line)

                elif re.match(r'^[A-Z]{2,}\s+[A-Z]{2,}', line):
                    # License type + cert e.g. "GEN CONT GCCO008766"
                    prof_data['license_type'] = line

            # ── OWNER SECTION ─────────────────────────────
            elif current_section == "owner":
                owner_line_count += 1

                if owner_line_count == 1:
                    # Remove trailing asterisk Accela adds
                    owner_data['name'] = line.replace(" *", "").strip()

                elif owner_line_count == 2:
                    owner_data['address'] = line

                elif owner_line_count == 3:
                    owner_data['city_state'] = line

                elif line.upper().startswith("EMAIL:"):
                    owner_data['email'] = line[6:].strip()

            prev_line = line

        # ── BUILD RESULT WITH PHILLIP'S COLUMN NAMES ─────
        license_type = prof_data.get('license_type', '')

        result = empty.copy()
        result['Name']           = prof_data.get('name', '')
        result['Title_Owner']    = owner_data.get('name', '')
        result['Email_Address']  = owner_data.get('email', '')
        result['Phone_Number']   = prof_data.get('phone', '')
        result['Website']        = ''
        result['Address']        = prof_data.get('address', '')
        result['License_Number'] = license_type
        result['Type']           = derive_type(license_type) if license_type else ''
        result['Company_Name']   = prof_data.get('company', '')
        result['Owner_Address']  = owner_data.get('address', '')
        result['Owner_City_State'] = owner_data.get('city_state', '')

        # Parse city / state / zip from "Atlanta, GA, 30350"
        city_line = prof_data.get('city_line', '')
        if city_line:
            parts = [p.strip() for p in city_line.split(',')]
            result['City']  = parts[0] if len(parts) > 0 else ''
            result['State'] = parts[1] if len(parts) > 1 else ''
            result['Zip']   = parts[2] if len(parts) > 2 else ''

        return result

    except Exception as e:
        print(f"  ERROR on {record_num}: {e}")
        return empty


# ── PHASE 3: TRANSFORM ────────────────────────────────────
def transform(records: list) -> pd.DataFrame:
    """
    Clean and deduplicate.
    Same contractor may have many permits — keep one row per contractor
    and add permit_count so client knows how active they are.
    More permits = busier contractor = better lead.
    """
    df = pd.DataFrame(records)

    # Drop rows where no contractor was found
    df = df[df['Name'] != '']

    if df.empty:
        return df

    # Count permits per contractor before deduplication
    counts = df.groupby('Name').size().reset_index(name='Permit_Count')
    df = df.merge(counts, on='Name', how='left')

    # Deduplicate — one row per unique license number
    # Fall back to contractor name if no license found
    df['dedup_key'] = df['License_Number'].where(
        df['License_Number'] != '', df['Name']
    )
    df.drop_duplicates(subset=['dedup_key'], keep='first', inplace=True)
    df.drop(columns=['dedup_key'], inplace=True)

    # Strip whitespace from all text columns
    str_cols = df.select_dtypes(include='object').columns
    df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())
    df.reset_index(drop=True, inplace=True)

    return df


# ── PHASE 4: LOAD ─────────────────────────────────────────
def load(df: pd.DataFrame, output_path: str):
    """Save final CSV with Phillip's columns first."""
    # Put Phillip's required columns first, then extras
    phillip_cols = ['Name', 'Title_Owner', 'Email_Address', 'Phone_Number',
                    'Website', 'City', 'Address', 'License_Number', 'Type']
    extra_cols   = ['Company_Name', 'State', 'Zip', 'Owner_Address',
                    'Owner_City_State', 'Permit_Count', 'Record_Number',
                    'Record_Type', 'Permit_Date', 'Permit_Status']

    ordered_cols = [c for c in phillip_cols if c in df.columns] + \
                   [c for c in extra_cols   if c in df.columns]

    df[ordered_cols].to_csv(output_path, index=False)
    print(f"\n✅  Saved {len(df)} unique contractor leads → {output_path}")


# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":

    print("=" * 55)
    print(" ATLANTA CONTRACTOR LEAD SCRAPER v5")
    print(f" Mode: {'TEST - first ' + str(TEST_LIMIT) + ' records' if TEST_LIMIT else 'FULL RUN - all 964 records'}")
    print("=" * 55)

    # Step 1 — Load record numbers from downloaded CSV
    records = load_record_numbers(INPUT_CSV, limit=TEST_LIMIT)

    # Step 2 — Scrape each permit detail page
    all_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Visible browser
        page = browser.new_page()

        for i, record in enumerate(records):
            print(f"[{i+1}/{len(records)}] Scraping {record['record_number']}...")
            data = scrape_record(page, record)
            all_data.append(data)
            print(f"         Name         : {data.get('Name') or '--- not found ---'}")
            print(f"         Company      : {data.get('Company_Name') or ''}")
            print(f"         Phone        : {data.get('Phone_Number') or ''}")
            print(f"         City         : {data.get('City') or ''}")
            print(f"         License      : {data.get('License_Number') or ''}")
            print(f"         Type         : {data.get('Type') or ''}")
            print(f"         Owner        : {data.get('Title_Owner') or ''}")
            print(f"         Owner Email  : {data.get('Email_Address') or ''}")
            time.sleep(DELAY)

        browser.close()

    print(f"\nExtracted {len(all_data)} raw records")

    # Step 3 — Clean and deduplicate
    clean_df = transform(all_data)
    print(f"After deduplication: {len(clean_df)} unique contractors")

    # Step 4 — Save
    if not clean_df.empty:
        load(clean_df, OUTPUT_CSV)
        print("\nSample output:")
        print(clean_df[['Name', 'Company_Name', 'Phone_Number',
                         'City', 'Type', 'Email_Address']].to_string())
    else:
        print("\n⚠️  No contractors found — saving raw data for inspection")
        raw_df = pd.DataFrame(all_data)
        raw_path = OUTPUT_CSV.replace('.csv', '_raw.csv')
        raw_df.to_csv(raw_path, index=False)
        print(f"Raw data saved to: {raw_path}")
