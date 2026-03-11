"""
GA SOS Full Scraper — All 16 license types, all pages, active + deduped CSV.
Uses Playwright browser for search (handles reCAPTCHA + Cloudflare),
browser fetch() for detail API calls (stays inside Cloudflare session).
"""
import asyncio, csv, json, re, time, random, urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BASE_URL = "https://goals.sos.ga.gov/GASOSOneStop/s/licensee-search"
AURA_URL = "https://goals.sos.ga.gov/GASOSOneStop/s/sfsites/aura"
OPT_SEL  = 'lightning-base-combobox-item[role="option"]'

SEARCH_COMBOS = [
    ("Architects & Interior Designers",              "Registered Architect"),
    ("Architects & Interior Designers",              "Registered Interior Designer"),
    ("Electrical Contractors",                       "Electrical Contractor- Non Restricted"),
    ("Electrical Contractors",                       "Electrical Contractor-Restricted"),
    ("Landscape Architects",                         "Landscape Architect"),
    ("Master & Journeyman Plumbers",                 "Journeyman Plumber"),
    ("Master & Journeyman Plumbers",                 "Master Plumber - Non-Restricted"),
    ("Master & Journeyman Plumbers",                 "Master Plumber - Restricted"),
    ("Residential & Commercial General Contractors", "Commercial General Contractor Individual"),
    ("Residential & Commercial General Contractors", "Commercial General Contractor Limited Tier Individual"),
    ("Residential & Commercial General Contractors", "Commercial General Contractor Limited Tier Qualifying Agent"),
    ("Residential & Commercial General Contractors", "Commercial General Contractor Qualifying Agent"),
    ("Residential & Commercial General Contractors", "Residential Basic Individual"),
    ("Residential & Commercial General Contractors", "Residential Basic Qualifying Agent"),
    ("Residential & Commercial General Contractors", "Residential Light Commercial Individual"),
    ("Residential & Commercial General Contractors", "Residential Light Commercial Qualifying Agent"),
]

FIELDNAMES = [
    "Name", "Title_Owner", "Email_Address", "Phone_Number", "Website",
    "City", "State", "Zip", "Address",
    "License_Number", "Type", "License_Status", "Issued_Date", "Expiry_Date",
]

# ── Playwright helpers ─────────────────────────────────────────────────────────

async def open_cb(page, index, wait_enabled=False):
    btn = page.locator("lightning-combobox >> button").nth(index)
    if wait_enabled:
        for _ in range(20):
            if (await btn.get_attribute("aria-disabled") or "").lower() != "true":
                break
            await page.wait_for_timeout(500)
    for attempt in range(5):
        await btn.click()
        await page.wait_for_timeout(1500 + attempt * 500)
        if await page.locator(OPT_SEL).count() > 0:
            return True
    return False

async def extract_rows(page):
    rows = page.locator("table tbody tr")
    count = await rows.count()
    result = []
    for i in range(count):
        row = rows.nth(i)
        link = row.locator("a[data-id]").first
        data_id = ""
        if await link.count() > 0:
            data_id = await link.get_attribute("data-id") or ""
        cells = await page.evaluate("""(row) => {
            const out = {};
            row.querySelectorAll('td[data-label]').forEach(td => {
                out[td.getAttribute('data-label')] = td.getAttribute('title') || td.textContent.trim();
            });
            return out;
        }""", await row.element_handle())
        result.append({
            "data_id":        urllib.parse.unquote(data_id),
            "Name":           cells.get("FULL NAME", ""),
            "License_Number": cells.get("LICENSE NUMBER", ""),
            "Type":           cells.get("LICENSE TYPE", ""),
            "License_Status": cells.get("STATUS", ""),
            "City":           cells.get("CITY", ""),
        })
    return result

async def search_and_collect(page, profession, lic_type):
    """Run one search and collect ALL pages of results."""
    await page.goto(BASE_URL, wait_until="load", timeout=45_000)
    # Wait for combobox to be ready
    try:
        await page.wait_for_selector("lightning-combobox", timeout=20_000)
    except PWTimeout:
        pass
    await page.wait_for_timeout(3000)

    if not await open_cb(page, 0):
        print(f"  ERROR: Could not open profession dropdown"); return []
    await page.locator(f'lightning-base-combobox-item[data-value="{profession}"]').first.click()
    await page.wait_for_timeout(2500)

    if not await open_cb(page, 1, wait_enabled=True):
        print(f"  ERROR: Could not open license type dropdown"); return []

    loc = page.locator(f'lightning-base-combobox-item[data-value="{lic_type}"]')
    if await loc.count() == 0:
        print(f"  ERROR: License type not found: {lic_type}"); return []
    await loc.first.click()
    await page.wait_for_timeout(1000)

    await page.locator('button:has-text("Search")').first.click()
    await page.wait_for_timeout(5000)

    try:
        await page.wait_for_selector("table tbody tr", timeout=15_000)
    except PWTimeout:
        print(f"  No results"); return []

    all_rows = []
    page_num = 0
    while True:
        page_num += 1
        rows = await extract_rows(page)
        all_rows.extend(rows)
        print(f"    Page {page_num}: {len(rows)} rows (total so far: {len(all_rows)})")

        # Salesforce LWC pagination — aria-label="Navigate to Next Page", title="next"
        nxt = page.locator('button[aria-label="Navigate to Next Page"]').or_(
              page.locator('button[title="next"]'))
        found_next = False
        if await nxt.count() > 0 and await nxt.first.is_enabled():
            await nxt.first.click()
            found_next = True

        if found_next:
            await page.wait_for_timeout(2500)
            try:
                await page.wait_for_selector("table tbody tr", timeout=10_000)
            except PWTimeout:
                break
        else:
            break

    return all_rows

# ── Detail API via browser fetch() ────────────────────────────────────────────

async def fetch_detail(page, encrypted_id, session):
    action = {
        "id": "1;a",
        "descriptor": "aura://ApexActionController/ACTION$execute",
        "callingDescriptor": "UNKNOWN",
        "params": {
            "namespace": "",
            "classname": "GASOS_LicenseeSearchController",
            "method": "fetchAllLicenseeDetails",
            "params": {"licenseNumber": encrypted_id},
            "cacheable": False,
            "isContinuation": False,
        },
    }
    aura_ctx = {
        "mode": "PROD",
        "fwuid": session.get("fwuid", ""),
        "app": "siteforce:communityApp",
        "loaded": session.get("loaded", {}),
        "dn": [], "globals": {}, "uad": True,
    }
    body = urllib.parse.urlencode({
        "message":      json.dumps({"actions": [action]}),
        "aura.context": json.dumps(aura_ctx),
        "aura.pageURI": "/GASOSOneStop/s/licensee-search",
        "aura.token":   "null",
    })
    scope_id = session.get("page_scope_id", "")

    try:
        result = await page.evaluate("""async ({url, body, scopeId}) => {
            const h = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'};
            if (scopeId) h['x-sfdc-page-scope-id'] = scopeId;
            const r = await fetch(url, {method: 'POST', headers: h, body, credentials: 'include'});
            return await r.text();
        }""", {"url": f"{AURA_URL}?r=1&aura.ApexAction.execute=1", "body": body, "scopeId": scope_id})

        data = json.loads(result)
        for action_resp in data.get("actions", []):
            rv    = action_resp.get("returnValue", {})
            inner = rv.get("returnValue", rv) if isinstance(rv, dict) else {}
            ld    = inner.get("licenseeDetails", {}) if isinstance(inner, dict) else {}
            pli   = inner.get("primaryLicenseInfo", {}) if isinstance(inner, dict) else {}
            if not ld:
                continue
            name = (ld.get("facilityName") or
                    " ".join(filter(None, [ld.get("firstName",""), ld.get("middleName",""), ld.get("lastName","")])))
            city  = ld.get("otherCity", "")
            state = ld.get("otherState", "")
            zipcd = ld.get("otherPostalCode", "")
            return {
                "Name":           name.strip(),
                "Title_Owner":    (ld.get("owner") or "").strip(),
                "Email_Address":  "",
                "Phone_Number":   "",
                "Website":        "",
                "City":           city.strip(),
                "State":          state.strip(),
                "Zip":            zipcd.strip(),
                "Address":        ", ".join(filter(None, [city, state, zipcd])),
                "License_Number": pli.get("licenseNumber", ""),
                "Type":           pli.get("licenseType", ""),
                "License_Status": pli.get("status", ""),
                "Issued_Date":    pli.get("issuedDate", ""),
                "Expiry_Date":    pli.get("expiryDate", ""),
            }
    except Exception as e:
        print(f"    fetch_detail error: {e}")
    return None

# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    t_start = time.time()
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent
    raw_csv  = out_dir / f"ga_sos_raw_{stamp}.csv"
    dedup_csv = out_dir / f"ga_sos_active_deduped_{stamp}.csv"

    session = {}

    def on_request(req):
        if "aura" in req.url and "ApexAction" in req.url and not session.get("fwuid"):
            pd  = req.post_data or ""
            dec = urllib.parse.unquote(pd)
            m   = re.search(r"aura\.context=(\{[^&]+\})", dec)
            if m:
                try:
                    ctx = json.loads(m.group(1))
                    session["fwuid"]  = ctx.get("fwuid", "")
                    session["loaded"] = ctx.get("loaded", {})
                    print(f"  Session: fwuid captured")
                except Exception:
                    pass
        if "aura" in req.url and not session.get("page_scope_id"):
            pid = req.headers.get("x-sfdc-page-scope-id", "")
            if pid:
                session["page_scope_id"] = pid
                print(f"  Session: page_scope_id captured")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel="chrome", headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        page.on("request", on_request)

        # Collect all active rows across all combos
        all_active = []

        for idx, (profession, lic_type) in enumerate(SEARCH_COMBOS, 1):
            t_combo = time.time()
            print(f"\n[{idx:2d}/16] {profession} / {lic_type}")
            rows = await search_and_collect(page, profession, lic_type)
            active = [r for r in rows if r["License_Status"].strip().lower() == "active"]
            print(f"  Total: {len(rows)}  Active: {len(active)}  ({time.time()-t_combo:.0f}s)")
            for r in active:
                r["_combo"] = lic_type
            all_active.extend(active)
            # Polite pause between searches
            await page.wait_for_timeout(random.randint(3000, 5000))

        print(f"\n{'='*60}")
        print(f"Phase 1 done: {len(all_active)} active rows across all combos")
        print(f"Phase 2: Fetching details via browser fetch()...")

        # Phase 2: detail API calls
        seen   = set()
        raw_rows   = []
        dedup_rows = []
        total = len(all_active)

        for i, row in enumerate(all_active):
            enc_id = row.get("data_id", "")
            if not enc_id:
                print(f"  [{i+1}/{total}] No data-id — skipping {row.get('Name','')}")
                continue

            detail = await fetch_detail(page, enc_id, session)
            if detail:
                rec = detail
            else:
                rec = {f: "" for f in FIELDNAMES}
                rec.update({k: row.get(k, "") for k in FIELDNAMES if k in row})

            raw_rows.append(rec)
            # GA-only filter
            state = rec.get("State", "").strip().lower()
            zip_  = rec.get("Zip", "").strip()
            is_ga = state in ("ga", "georgia") or zip_.startswith("3")
            key = (rec.get("License_Number","").strip(), rec.get("Name","").strip())
            if is_ga and key not in seen:
                seen.add(key)
                dedup_rows.append(rec)

            elapsed = time.time() - t_start
            print(f"  [{i+1:4d}/{total}] {rec['Name'][:32]:32s} | {rec['License_Number']:12s} | {rec.get('City','')}, {rec.get('State','')} {rec.get('Zip','')} | {rec['License_Status']}  ({elapsed:.0f}s)")

            # Polite delay between detail calls
            await asyncio.sleep(random.uniform(1.0, 2.0))

        await browser.close()

    # Save CSVs
    with open(raw_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(raw_rows)

    with open(dedup_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(dedup_rows)

    t_total = time.time() - t_start
    mins, secs = divmod(int(t_total), 60)

    print(f"\n{'='*60}")
    print(f"DONE in {mins}m {secs}s")
    print(f"Raw ({len(raw_rows)} rows):    {raw_csv}")
    print(f"Deduped ({len(dedup_rows)} rows): {dedup_csv}")

asyncio.run(run())
