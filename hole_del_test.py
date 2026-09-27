"""Einmaliger Test 2: Aufbau von Spielplan und Spieldetails bei penny-del.org.
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


def eng(s):
    return re.sub(r"\s+", " ", s).strip()


def ohne_tags(s):
    return eng(re.sub(r"<[^>]+>", " ", s))


def zeilen_der_tabelle(html, n=3):
    """Zeigt die ersten n Tabellenzeilen nach der Spielplan-Kopfzeile."""
    p = html.find("team-schedule__compet")
    if p < 0:
        log("  keine Spielplantabelle")
        return []
    rest = html[p:]
    rows = re.findall(r"<tr[^>]*>.*?</tr>", rest, re.S)
    log(f"  Zeilen in der Tabelle: {len(rows)}")
    for r in rows[1:n + 1]:
        log("  ROH:", eng(r)[:1500])
        log("  TEXT:", ohne_tags(r)[:300])
    return rows


os.makedirs("daten", exist_ok=True)

log("===== A. Spielplan einer Mannschaft 2025-26 (Team 2)")
h = holen("/statistik/saison-2025-26/hauptrunde/spielplan/team/2")
links = re.findall(r'/statistik/spieldetails/[^"\'#?\s]+', h)
log("Detail-Links:", len(links), "davon verschieden:", len(set(links)))
rows = zeilen_der_tabelle(h, 2)
if rows:
    log("  LETZTE TEXT:", ohne_tags(rows[-1])[:300])
opts = re.findall(r'<option value="(/statistik/saison-2025-26/hauptrunde/spielplan/team/\d+)"[^>]*>([^<]+)<', h)
log("Team-Auswahl:", len(opts), "|", "; ".join(f"{u.rsplit('/', 1)[1]}={n.strip()}" for u, n in opts))
alle_opt = sorted(set(re.findall(r'<option value="(/statistik/[^"]+)"', h)))
log("Alle Optionen:", len(alle_opt))
for o in alle_opt[:60]:
    log("  opt", o)

log("===== B. Spielplan 2025-26 gesamt: Zeilen mit und ohne Link")
h = holen("/statistik/saison-2025-26/hauptrunde/spielplan")
zeilen_der_tabelle(h, 2)

log("===== C. Spielplan 2026-27 (kommende Spiele)")
h = holen("/statistik/saison-2026-27/hauptrunde/spielplan")
rows = zeilen_der_tabelle(h, 1)
for r in rows:
    if "spieldetails" not in r and "Datum" not in r:
        log("  OHNE LINK ROH:", eng(r)[:1500])
        break
log("Detail-Links:", len(set(re.findall(r'/statistik/spieldetails/[^"\'#?\s]+', h))))

log("===== D. Spieldetails: alle Statistik-Balken")
d = holen("/statistik/spieldetails/25092026_straubing-tigers_gg_erc-ingolstadt_4409")
for t, a, b in re.findall(r'progress-labels__title">([^<]+)</div>.*?progress-labels__value">([^<]*)</div>\s*'
                          r'<div class="progress-labels__value">([^<]*)</div>', d, re.S):
    log(f"  STAT {t.strip()} = {a.strip()} : {b.strip()}")
for w in ("alc-event-scoreboard", "Endstand", "n.V.", "n.P.", "OT", "SO", "Drittel", "datetime",
          "alc-event-info__title", "shots-on-goal", "Torschüsse", "Schüsse auf"):
    p = d.find(w, 5000)  # hinter der Kopfleiste suchen
    if p > 0:
        log(f"--- Umfeld '{w}' @{p}")
        log(eng(d[max(0, p - 300): p + 1200]))
for t, v in re.findall(r'alc-event-info__title">([^<]+)</span>\s*<span class="alc-event-info__value">([^<]*)<', d):
    log(f"  INFO {t.strip()} = {eng(v)}")

log("===== E. Schuss-Unterseite")
d2 = holen("/statistik/spieldetails/25092026_straubing-tigers_gg_erc-ingolstadt_4409/shots")
p = d2.find("gamedetail-content")
log(ohne_tags(d2[p:p + 20000])[:1500] if p > 0 else "kein Inhalt")

log("===== F. Kurz-URLs")
for u in ("/statistik/spieldetails/x_4000", "/statistik/spieldetails/_4000",
          "/statistik/saison-2025-26/playoffs/spielplan"):
    holen(u)

with open("daten/del-test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(bericht))
print("fertig")
