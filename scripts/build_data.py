#!/usr/bin/env python3
"""Download USCIS H-1B Employer Data Hub CSVs, keep medtech/healthcare employers, write docs/data.json."""
import csv, io, json, re, sys, datetime, urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data" / "raw", ROOT / "docs" / "data.json"
PAGES = ["https://www.uscis.gov/archive/h-1b-employer-data-hub-files",
         "https://www.uscis.gov/h-1b-employer-data-hub-files"]
GUESS = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{y}.csv"
KEEP_YEARS = 3
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# USCIS only gives a 2-digit NAICS code, so sectors are matched by NAICS + employer-name keywords.
# EDIT THESE LISTS to tune results. First match wins.
CATEGORIES = [
 ("Surgical Robotics", r"surgical robot|intuitive surgical|auris|verb surgical|procept|titan medical|vicarious surg|asensus|corindus|stereotaxis|monogram|mako|medical robot|robotic[s]? (surg|med|health)|(surg|med|health)\w* robot"),
 ("Wearables", r"wearable|fitbit|oura|whoop|masimo|dexcom|irhythm|biosensor|biointellisense|empatica|withings|senseonics|insulet|tandem diabetes|vital ?connect|glucose"),
 ("Healthcare", r"hospital|clinic|medical center|health system|physician|nursing|pediatric|oncology|children'?s|healthcare|health care|university.*health|kaiser|mayo"),
 ("Medical Device", r"medical|medtronic|abbott|boston scientific|stryker|zimmer|edwards life|biomet|orthop|implant|cardio|vascular|spine|surgical|diagnostic|biomed|catheter|dental|imaging|ultrasound|neuro|prosthe|medtech|hologic|baxter|becton|resmed|smith ?& ?nephew|globus|nuvasive|penumbra|align tech|philips|ge healthcare|siemens health"),
 ("Healthcare", r"health|pharma|therapeutic|biotech|care\b"),
]

def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()

def decode(b):
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"): return b.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("latin-1")

def discover():
    links = {}
    for p in PAGES:
        try: html = fetch(p).decode("utf-8", "ignore")
        except Exception as e: print("WARN page", p, e); continue
        for href in re.findall(r'href="([^"]+\.csv)"', html, re.I):
            y = re.search(r"(20\d\d)", href)
            if y and re.search(r"h-?1b", href, re.I): links[int(y.group(1))] = urljoin(p, href)
    if not links:  # fallback: guess the standard file name
        now = datetime.date.today().year
        for y in range(now, now - 5, -1):
            try: fetch(GUESS.format(y=y)); links[y] = GUESS.format(y=y)
            except Exception: pass
    return links

def num(s): return int(re.sub(r"[^\d]", "", s or "") or 0)

def parse(text, fy_hint):
    first = text.split("\n", 1)[0]
    rd = csv.DictReader(io.StringIO(text), delimiter="\t" if first.count("\t") > first.count(",") else ",")
    cols = {}
    for h in rd.fieldnames or []:
        l = h.lower()
        for key, pat in [("fy","fiscal"),("name","employer"),("ia","initial approv"),("id","initial denial"),
                         ("ca","continuing approv"),("cd","continuing denial"),("naics","naics"),("state","state"),("city","city")]:
            if pat in l and key not in cols: cols[key] = h
    for r in rd:
        g = lambda k: (r.get(cols.get(k, ""), "") or "").strip()
        yield dict(fy=num(g("fy")) or fy_hint, name=g("name").upper(), ia=num(g("ia")), id=num(g("id")),
                   ca=num(g("ca")), cd=num(g("cd")), naics=g("naics")[:2], state=g("state"), city=g("city").title())

def categorize(name, naics):
    for cat, rx in CATEGORIES:
        if re.search(rx, name, re.I): return cat
    return "Healthcare" if naics == "62" else None

def main():
    RAW.mkdir(parents=True, exist_ok=True)
    files = {int(re.search(r"(20\d\d)", f.name).group(1)): f.read_bytes() for f in RAW.glob("*.csv") if re.search(r"20\d\d", f.name)}
    for y, url in sorted(discover().items(), reverse=True)[:KEEP_YEARS]:
        if y in files: continue
        try: files[y] = fetch(url); print("downloaded", y, url)
        except Exception as e: print("WARN download", y, e)
    years = sorted(files, reverse=True)[:KEEP_YEARS]
    if not years: sys.exit("No data obtained - keeping previous data.json")
    agg = {}
    for y in years:
        for r in parse(decode(files[y]), y):
            if not r["name"]: continue
            cat = categorize(r["name"], r["naics"])
            if not cat: continue
            a = agg.setdefault((r["name"], r["state"]), dict(n=r["name"].title(), s=r["state"], c=r["city"], cat=cat, ia=0, ca=0, d=0, y={}))
            a["ia"] += r["ia"]; a["ca"] += r["ca"]; a["d"] += r["id"] + r["cd"]
            a["y"][str(y)] = a["y"].get(str(y), 0) + r["ia"] + r["ca"]
    rows = sorted((a for a in agg.values() if a["ia"] + a["ca"] > 0), key=lambda a: -(a["ia"] + a["ca"]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(dict(updated=datetime.datetime.utcnow().isoformat(timespec="minutes") + "Z",
                                   years=years, rows=rows), separators=(",", ":")))
    print("wrote", len(rows), "employers for FY", years)

if __name__ == "__main__": main()
