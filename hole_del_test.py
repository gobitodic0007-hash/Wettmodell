"""Einmaliger Test: Was liefert penny-del.org an GitHub aus?
Schreibt einen Bericht nach daten/del-test.txt. Wird danach wieder geloescht."""
import os
import re
import urllib.request

BASIS = "https://www.penny-del.org"
KOPF = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9"}
bericht = []


def log(*t):
    s = " ".join(str(x) for x in t)
    print(s)
    bericht.append(s)


def holen(pfad):
    url = pfad if pfad.startswith("http") else BASIS + pfad
    try:
        req = urllib.request.Request(url, headers=KOPF)
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
            log(f"OK {r.status} {len(html)} Zeichen  {url}")
            return html
    except Exception as e:
        log(f"FEHLER {type(e).__name__} {getattr(e, 'code', '')}  {url}")
        return ""


def umfeld(html, wort, n=2, breite=700):
    pos = [m.start() for m in re.finditer(re.escape(wort), html)][:n]
    for p in pos:
        log(f"--- Umfeld '{wort}' @{p}")
        log(re.sub(r"\s+", " ", html[max(0, p - breite // 3): p + breite]))


def datenquellen(html):
    urls = set(re.findall(r"""["'](https?://[^"']+|/[^"'\s]*(?:api|json|ajax|eID|type=)[^"']*)["']""", html))
    for u in sorted(urls):
        if any(k in u.lower() for k in ("api", "json", "ajax", "eid", "type=", "data", "stat")):
            log("  Quelle?", u[:200])
    for s in sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', html)))[:30]:
        log("  script", s[:200])
    for a in sorted(set(re.findall(r'data-[a-z-]+="[^"]{3,200}"', html)))[:40]:
        log("  attr", a)


os.makedirs("daten", exist_ok=True)

log("===== 1. Spieleseite")
h = holen("/spiele")
links = sorted(set(re.findall(r'/statistik/spieldetails/[^"\'#?\s]+', h)))
log("Spieldetail-Links:", len(links))
for l in links[:5]:
    log("  ", l)
datenquellen(h)
umfeld(h, "spieldetails", 1, 1500)

for saison in ("2025-26", "2024-25"):
    log(f"===== 2. Spielplan {saison}")
    h = holen(f"/statistik/saison-{saison}/hauptrunde/spielplan")
    l2 = sorted(set(re.findall(r'/statistik/spieldetails/[^"\'#?\s]+', h)))
    log("Spieldetail-Links:", len(l2))
    for l in l2[:3] + l2[-3:]:
        log("  ", l)
    ids = sorted(int(x) for x in re.findall(r'/statistik/spieldetails/[^"\']*_(\d+)["\']', h))
    if ids:
        log("IDs von", ids[0], "bis", ids[-1])
    for w in ("Spieltag", "page", "mehr laden", "Mehr", "pagination", "select"):
        if w in h:
            umfeld(h, w, 1, 500)
    datenquellen(h)

log("===== 3. Spieldetails")
ziel = links[0] if links else "/statistik/spieldetails/25092026_straubing-tigers_gg_erc-ingolstadt_4409"
h = holen(ziel)
for w in ("Torsch", "Schüsse", "Strafminuten", "Bully", "Überzahl", "Drittel", "Paraden", "Zuschauer"):
    umfeld(h, w, 1, 900)
datenquellen(h)

log("===== 4. Teamstatistik und Tabelle")
for p in ("/statistik/saison-2026-27/hauptrunde/teamstats", "/tabelle"):
    h = holen(p)
    umfeld(h, "Schüsse", 1, 900)
    datenquellen(h)

with open("daten/del-test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(bericht))
print("fertig")
