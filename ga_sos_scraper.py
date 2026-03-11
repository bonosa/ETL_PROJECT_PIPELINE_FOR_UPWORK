"""
Georgia Secretary of State Professional Licensee Scraper
Target: https://goals.sos.ga.gov/GASOSOneStop/s/licensee-search
Salesforce LWC (Lightning Web Components) — shadow DOM

Confirmed selectors (from DOM probe):
  - Open combobox   : lightning-combobox >> button    (nth 0=profession, 1=license type)
  - Options         : lightning-base-combobox-item[role="option"]  (data-value attr)
  - Search button   : button:has-text("Search")
  - Results table   : table tbody tr
"""

import asyncio, csv, re, logging, sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

BASE_URL  = "https://goals.sos.ga.gov/GASOSOneStop/s/licensee-search"
OPT_SEL   = 'lightning-base-combobox-item[role="option"]'

FIELDNAMES = [
    "Name", "Title_Owner", "Email_Address", "Phone_Number",
    "Website", "City", "Address", "License_Number", "Type", "License_Status",
]

# Statuses that mean the license is NOT active — skip these rows entirely
INACTIVE_KEYWORDS = {"inactive", "expired", "revoked", "suspended", "cancelled",
                     "terminated", "lapsed", "void", "denied"}

# Profession / License-type pairs.  None = enumerate all available types.
SEARCH_COMBOS = [
    ("Architects & Interior Designers",              "Registered Architect"),
    ("Architects & Interior Designers",              "Interior Designer"),
    ("Electrical Contractors",                       "Electrical Contractor - Unrestricted"),
    ("Electrical Contractors",                       "Electrical Contractor - Restricted"),
    ("Landscape Architects",                         "Landscape Architect"),
    ("Master & Journeyman Plumbers",                 "Journeyman Plumber"),
    ("Master & Journeyman Plumbers",                 "Master Plumber - Non-Restricted"),
    ("Master & Journeyman Plumbers",                 "Master Plumber - Restricted"),
    ("Residential & Commercial General Contractors", None),
]

GA_RE = [re.compile(p, re.I) for p in [
    r",\s*GA\b", r",\s*Georgia\b", r"\bGA\s+\d{5}",
]]

def is_ga(text: str) -> bool:
    if not text:
        return True
    return any(p.search(text) for p in GA_RE)

def ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

# ── Combobox helpers ──────────────────────────────────────────────────────────

async def wait_opts_visible(page: Page, timeout=12_000) -> int:
    """Wait until at least one lightning-base-combobox-item is visible. Returns count."""
    end = asyncio.get_event_loop().time() + timeout / 1000
    while asyncio.get_event_loop().time() < end:
        try:
            await page.wait_for_selector(OPT_SEL, state="visible", timeout=2_000)
            return await page.locator(OPT_SEL).count()
        except PWTimeout:
            await page.wait_for_timeout(500)
    return 0

async def open_cb(page: Page, index: int, retries=3) -> bool:
    """Click the button inside lightning-combobox[index] to open its dropdown."""
    for attempt in range(retries):
        try:
            await page.locator("lightning-combobox >> button").nth(index).click()
            await page.wait_for_timeout(1500)
            n = await wait_opts_visible(page, timeout=8_000)
            if n > 0:
                return True
            log.warning(f"  CB{index} open attempt {attempt+1}: no visible options yet")
            await page.wait_for_timeout(1500)
        except Exception as e:
            log.warning(f"  CB{index} open attempt {attempt+1} error: {e}")
            await page.wait_for_timeout(1000)
    return False

async def pick_opt(page: Page, text: str) -> bool:
    """Click the option whose inner_text contains `text`."""
    items = page.locator(OPT_SEL)
    count = await items.count()
    # First try data-value exact match (fast)
    dv = page.locator(f'lightning-base-combobox-item[data-value="{text}"]')
    if await dv.count() > 0:
        await dv.first.click()
        await page.wait_for_timeout(1500)
        return True
    # Fall back: iterate and match by inner_text
    for i in range(count):
        try:
            t = (await items.nth(i).inner_text()).strip()
            if text.lower() in t.lower():
                log.info(f"    Clicking {t!r}")
                await items.nth(i).click()
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    log.warning(f"  Option '{text}' not found among {count} items")
    return False

async def list_opts(page: Page, cb_index: int) -> list[str]:
    """Return all option texts for combobox at index."""
    if not await open_cb(page, cb_index):
        return []
    items = page.locator(OPT_SEL)
    count = await items.count()
    texts = []
    for i in range(count):
        try:
            t = (await items.nth(i).inner_text()).strip()
            if t:
                texts.append(t)
        except Exception:
            pass
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(800)
    return texts

async def select_combo(page: Page, cb_index: int, text: str) -> bool:
    if not await open_cb(page, cb_index):
        return False
    return await pick_opt(page, text)

# ── Page load / search ────────────────────────────────────────────────────────

async def load_search(page: Page):
    await page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(2_000)

async def click_search(page: Page) -> bool:
    btn = page.locator('button:has-text("Search"), button:has-text("SEARCH")')
    if await btn.count() == 0:
        return False
    await btn.first.click()
    await page.wait_for_timeout(3_000)
    return True

# ── Detail extraction ─────────────────────────────────────────────────────────

async def grab(page: Page, *selectors) -> str:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                t = (await loc.inner_text()).strip()
                if t:
                    return t
        except Exception:
            pass
    return ""

async def extract_detail(page: Page, lic_type: str) -> dict:
    r = {f: "" for f in FIELDNAMES}
    r["Type"] = lic_type
    await page.wait_for_timeout(2_000)

    # ── Strategy A: lightning-output-field by field-name ─────────────────────
    field_map = {
        "Name":           ["Name", "FullName", "Full_Name__c", "Account_Name__c"],
        "Title_Owner":    ["Title", "Title__c", "Contact_Name__c", "Owner_Name__c"],
        "Email_Address":  ["Email", "Email__c", "PersonEmail"],
        "Phone_Number":   ["Phone", "Phone__c", "MobilePhone", "Phone_Number__c"],
        "Website":        ["Website", "Website__c"],
        "City":           ["City", "BillingCity", "MailingCity", "City__c"],
        "Address":        ["BillingStreet","MailingStreet","Street","Address__c","BillingAddress"],
        "License_Number": ["License_Number__c","LicenseNumber","License_No__c","Name"],
        "License_Status": ["Status", "License_Status__c", "License_Status", "Status__c"],
    }
    for col, fnames in field_map.items():
        for fn in fnames:
            v = await grab(page,
                f'lightning-output-field[field-name="{fn}"] .slds-form-element__static',
                f'lightning-output-field[field-name="{fn}"] span',
                f'[data-field="{fn}"] .slds-form-element__static',
            )
            if v:
                r[col] = v
                break

    # ── Strategy B: label → value scan ───────────────────────────────────────
    lbl_to_col = {
        "name":"Name","full name":"Name","licensee name":"Name",
        "title":"Title_Owner","owner":"Title_Owner","contact":"Title_Owner",
        "email":"Email_Address","email address":"Email_Address",
        "phone":"Phone_Number","phone number":"Phone_Number","mobile":"Phone_Number",
        "website":"Website","url":"Website",
        "city":"City",
        "address":"Address","street":"Address","mailing address":"Address",
        "license number":"License_Number","license #":"License_Number","license no":"License_Number",
        "status":"License_Status","license status":"License_Status","license_status":"License_Status",
    }
    try:
        lbls = await page.locator('.slds-form-element__label, dt').all_inner_texts()
        vals = await page.locator('.slds-form-element__static, dd').all_inner_texts()
        for lbl, val in zip(lbls, vals):
            key = lbl.strip().lower().rstrip(":")
            col = lbl_to_col.get(key)
            if col and not r[col]:
                r[col] = val.strip()
    except Exception:
        pass

    # ── Strategy C: regex on full body text ──────────────────────────────────
    try:
        body = await page.inner_text("body")
        if not r["Phone_Number"]:
            m = re.search(r'\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}', body)
            if m: r["Phone_Number"] = m.group()
        if not r["Name"]:
            h1 = await grab(page, 'h1', '.slds-page-header__title', '.recordName')
            if h1: r["Name"] = h1
    except Exception:
        pass

    log.info(f"    → {r['Name']!r:40s} {r['License_Number']!r:20s} {r['City']!r}")
    return r

# ── Active filter on search form ─────────────────────────────────────────────

async def try_set_active(page: Page):
    """Best-effort: set Status = Active on the search form before clicking Search."""
    try:
        # 1. Check if a 3rd lightning-combobox button exists (Status dropdown)
        cb_count = await page.locator("lightning-combobox >> button").count()
        if cb_count >= 3:
            await open_cb(page, 2)
            items = page.locator(OPT_SEL)
            for i in range(await items.count()):
                t = (await items.nth(i).inner_text()).strip().lower()
                if t == "active":
                    await items.nth(i).click()
                    await page.wait_for_timeout(1_000)
                    log.info("  Status combobox set to Active")
                    return
            await page.keyboard.press("Escape")

        # 2. Check for a select element with "Active" option
        selects = page.locator('select')
        for i in range(await selects.count()):
            opts = await selects.nth(i).locator('option').all_inner_texts()
            if any("active" in o.lower() for o in opts):
                await selects.nth(i).select_option(label="Active")
                log.info("  <select> Status set to Active")
                return

        # 3. Check for radio button labelled "Active"
        radio = page.locator('input[type="radio"]')
        for i in range(await radio.count()):
            label = await page.locator(f'label[for="{await radio.nth(i).get_attribute("id")}"]').all_inner_texts()
            if any("active" in l.lower() for l in label):
                await radio.nth(i).click()
                log.info("  Radio 'Active' selected")
                return
    except Exception as e:
        log.debug(f"  try_set_active: {e}")


# ── Process result rows ───────────────────────────────────────────────────────

async def process_results(page: Page, lic_type: str,
                          raw_w: csv.DictWriter, ga_w: csv.DictWriter) -> int:
    total, page_num = 0, 0

    while True:
        page_num += 1
        log.info(f"  Results page {page_num}")

        try:
            await page.wait_for_selector('table tbody tr', timeout=20_000)
        except PWTimeout:
            log.info("  No result rows.")
            break

        rows = page.locator('table tbody tr')
        n = await rows.count()
        log.info(f"  {n} rows")
        if not n:
            break

        for i in range(n):
            try:
                rows = page.locator('table tbody tr')
                row  = rows.nth(i)
                rt   = (await row.inner_text()).strip()
                log.info(f"  Row {i}: {rt[:100]}")

                # ── Active-only pre-filter ────────────────────────────────────
                rt_lower = rt.lower()
                # Skip if row explicitly shows an inactive status keyword
                if any(kw in rt_lower for kw in INACTIVE_KEYWORDS):
                    log.info(f"  Row {i}: skipped (inactive status in row text)")
                    continue
                # If results table has a Status column, require "active" to be present
                # (only enforce when status words appear at all — avoids false negatives
                #  on rows that simply don't show status text)
                has_status_word = any(kw in rt_lower for kw in
                                      {"active", "inactive", "expired", "revoked",
                                       "suspended", "cancelled"})
                if has_status_word and "active" not in rt_lower:
                    log.info(f"  Row {i}: skipped (no 'active' in row text)")
                    continue

                # Locate SELECT button
                sel_btn = row.locator(
                    'button:has-text("Select"), a:has-text("Select"), '
                    'button:has-text("SELECT"), a:has-text("SELECT")'
                ).first

                if await sel_btn.count() == 0:
                    log.warning(f"  Row {i}: no SELECT button — skipping")
                    continue

                before_url = page.url
                await sel_btn.click()
                await page.wait_for_timeout(3_000)
                navigated = page.url != before_url

                if navigated:
                    rec = await extract_detail(page, lic_type)
                    raw_w.writerow(rec)
                    status = rec.get("License_Status", "").strip().lower()
                    # Keep if status is "active" or unknown (blank)
                    is_active = (not status) or (status == "active") or ("active" in status and not any(kw in status for kw in INACTIVE_KEYWORDS))
                    if is_active and is_ga(rec["Address"] + " " + rec["City"]):
                        ga_w.writerow(rec)
                    total += 1
                    await page.go_back(wait_until="networkidle", timeout=30_000)
                    await page.wait_for_timeout(1_500)
                    await page.wait_for_selector('table tbody tr', timeout=20_000)
                else:
                    # Modal
                    modal = page.locator('[role="dialog"]')
                    if await modal.count():
                        rec = {f: "" for f in FIELDNAMES}
                        rec["Type"] = lic_type
                        body = (await modal.first.inner_text()).strip()
                        lines = [l.strip() for l in body.splitlines() if l.strip()]
                        lbl_col = {
                            "name":"Name","phone":"Phone_Number","email":"Email_Address",
                            "city":"City","address":"Address","license number":"License_Number",
                        }
                        for j in range(0, len(lines)-1, 2):
                            key = lines[j].lower().rstrip(":")
                            col = lbl_col.get(key)
                            if col: rec[col] = lines[j+1]
                        raw_w.writerow(rec)
                        status = rec.get("License_Status", "").strip().lower()
                        is_active = (not status) or (status == "active") or ("active" in status and not any(kw in status for kw in INACTIVE_KEYWORDS))
                        if is_active and is_ga(rec["Address"] + " " + rec["City"]):
                            ga_w.writerow(rec)
                        total += 1
                        close = page.locator('[title="Close"], button:has-text("Close"), .slds-modal__close')
                        if await close.count():
                            await close.first.click()
                            await page.wait_for_timeout(800)
                    else:
                        log.warning(f"  Row {i}: no navigation & no modal")

            except Exception as e:
                log.error(f"  Row {i} error: {e}")
                try:
                    if BASE_URL.split("/")[2] not in page.url:
                        await page.go_back(wait_until="networkidle", timeout=15_000)
                        await page.wait_for_timeout(1_500)
                except Exception:
                    pass

        # Pagination
        nxt = page.locator(
            'button[title="Next Page"], button[name="Next"], '
            'a[title="Next Page"], button:has-text("Next >")'
        )
        if await nxt.count() > 0 and await nxt.first.is_enabled():
            await nxt.first.click()
            await page.wait_for_timeout(2_500)
        else:
            break

    return total

# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    stamp    = ts()
    out_dir  = Path(__file__).parent
    raw_path = out_dir / f"ga_sos_leads_raw_{stamp}.csv"
    ga_path  = out_dir / f"ga_sos_leads_GA_{stamp}.csv"
    log.info(f"Raw → {raw_path}")
    log.info(f"GA  → {ga_path}")

    with (
        open(raw_path, "w", newline="", encoding="utf-8") as rf,
        open(ga_path,  "w", newline="", encoding="utf-8") as gf,
    ):
        rw = csv.DictWriter(rf, fieldnames=FIELDNAMES); rw.writeheader()
        gw = csv.DictWriter(gf, fieldnames=FIELDNAMES); gw.writeheader()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1400, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            grand = 0

            for profession, lic_type in SEARCH_COMBOS:
                # Resolve "None" → enumerate all license types for this profession
                if lic_type is None:
                    log.info(f"\n{'='*60}\nEnumerating types for: {profession}")
                    await load_search(page)
                    if not await select_combo(page, 0, profession):
                        log.error(f"  Could not select profession, skipping"); continue
                    await page.wait_for_timeout(1_500)
                    types = await list_opts(page, 1)
                    types = [t for t in types if t.lower() not in ("--none--","none","")]
                    log.info(f"  Types found: {types}")
                else:
                    types = [lic_type]

                for lt in types:
                    log.info(f"\n{'='*60}\n{profession} / {lt}")
                    await load_search(page)

                    # Select profession
                    if not await select_combo(page, 0, profession):
                        log.error(f"  Profession select failed, skipping"); continue
                    # Wait for license type combobox to populate
                    await page.wait_for_timeout(2_000)

                    # Select license type
                    if not await select_combo(page, 1, lt):
                        log.warning(f"  License type select failed, trying search anyway")

                    # Try to set Status = Active on the form (if the field exists)
                    await try_set_active(page)

                    # Search
                    if not await click_search(page):
                        log.error("  Search button not found"); continue

                    count = await process_results(page, lt, rw, gw)
                    log.info(f"  Collected {count} records")
                    grand += count

            await browser.close()

    log.info(f"\n{'='*60}")
    log.info(f"DONE — total records: {grand}")
    log.info(f"Raw CSV : {raw_path}")
    log.info(f"GA  CSV : {ga_path}")

    # ── Dedup ─────────────────────────────────────────────────────────────────
    dedup = out_dir / f"ga_sos_leads_GA_deduped_{stamp}.csv"
    seen: set = set()
    with open(ga_path, newline="", encoding="utf-8") as rf, \
         open(dedup,   "w", newline="", encoding="utf-8") as wf:
        reader = csv.DictReader(rf)
        writer = csv.DictWriter(wf, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in reader:
            key = (row["License_Number"].strip(), row["Name"].strip())
            if key not in seen:
                seen.add(key)
                writer.writerow(row)
    log.info(f"Deduped : {dedup}  ({len(seen)} unique)")

if __name__ == "__main__":
    asyncio.run(run())
