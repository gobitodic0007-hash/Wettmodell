#!/usr/bin/env python3
"""Holt DEL-Daten von penny-del.org (Webseite, keine offizielle Schnittstelle).

Arbeitet ergaenzend: Spiele, die schon in der Datei stehen, werden nicht
erneut abgerufen. Der erste Lauf holt rund 1000 Spielseiten und dauert
etwa 10 bis 15 Minuten, jeder weitere nur noch Sekunden.

Erzeugt (gleicher Aufbau wie bei der NHL, damit die App beides gleich rechnet):
  daten/del-spiele.csv       Tore, Tore nach 60 Minuten, Schuesse aufs Tor, Strafminuten
  daten/del-ansetzungen.csv  kommende Spiele
"""

import csv, html, os, re, time, urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

BASIS = "https://www.penny-del.org"
ORDNER = "daten"
SPIELE = f"{ORDNER}/del-spiele.csv"
BERLIN = ZoneInfo("Europe/Berlin")
ZEITLIMIT = 25 * 60          # Sekunden fuer Spielseiten je Lauf, der Rest folgt beim naechsten
KOPF = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9"}

# Gleiche ersten Spalten wie nhl-spiele.csv, danach DEL-Zusatzwerte
KOPF_SPIELE = ["Datum", "GameId", "Saison", "Heim", "Gast",
               "HeimTore", "GastTore", "HeimReg", "GastReg", "Ende",
               "HeimSOG", "GastSOG", "HeimPIM", "GastPIM",
               "HeimTwId", "HeimTw", "GastTwId", "GastTw",
               "Spieltag", "HeimSchuesse", "GastSchuesse", "HeimPP", "GastPP",
               "HeimBully", "GastBully"]
KOPF_ANS = ["Zeit", "GameId", "Heim", "Gast", "Spieltag"]


def saisons():
    h = date.today()
    j = h.year if h.month >= 8 else h.year - 1
    return [f"{a}-{str(a + 1)[2:]}" for a in (j - 2, j - 1, j)]


def holen(pfad, versuche=3):
    url = pfad if pfad.startswith("http") else BASIS + pfad
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers=KOPF)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print("  404", url[:110])
                return ""
            fehler = f"HTTP {e.code}"
        except Exception as e:
            fehler = type(e).__name__
        if i == versuche - 1:
            print("  Fehler", fehler, url[:110])
            return ""
        time.sleep(3 * (i + 1))
    return ""


def text(s):
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).replace("﻿", "").strip()


def zahl(s):
    try:
        return int(str(s).strip().replace(".", ""))
    except Exception:
        return ""


# ---------------------------------------------------------------- Spielplan
def teamseiten(saison):
    h = holen(f"/statistik/saison-{saison}/hauptrunde/spielplan")
    pfade = sorted(set(re.findall(
        rf'value="(/statistik/saison-{saison}/hauptrunde/spielplan/team/\d+)"', h)))
    return pfade


ZEILE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def zeile_lesen(roh, saison, unbekannt):
    zellen = re.findall(r'<td class="([^"]+)"[^>]*>(.*?)</td>', roh, re.S)
    if not zellen:
        return None
    feld = {}
    for klasse, inhalt in zellen:
        feld.setdefault(klasse.split()[0], []).append(inhalt)
    try:
        tag = text(feld["team-schedule__date"][0])
        uhr = text(feld["team-schedule__time"][0])
        st = text(feld.get("team-schedule__compet", [""])[0])
        teams = feld["team-schedule__versus"]
        heim = text(re.search(r'team-meta__name[^>]*>(.*?)</h6>', teams[0], re.S).group(1))
        gast = text(re.search(r'team-meta__name[^>]*>(.*?)</h6>', teams[1], re.S).group(1))
    except Exception:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tag)
    if not m or not heim or not gast:
        return None
    iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    status = " ".join(text(x) for x in feld.get("team-schedule__status", []))
    link = re.search(r'href="(/statistik/spieldetails/[^"]+_(\d+))"', roh)
    spiel = {"datum": iso, "uhr": uhr, "spieltag": re.sub(r"\D", "", st),
             "heim": heim, "gast": gast, "saison": saison}
    erg = re.search(r"(\d+)\s*:\s*(\d+)", status)
    if not link or not erg:
        spiel["offen"] = True
        return spiel
    spiel["offen"] = False
    spiel["pfad"], spiel["id"] = link.group(1), link.group(2)
    hs, gs = int(erg.group(1)), int(erg.group(2))
    per = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*:\s*(\d+)", status[erg.end():])]
    if len(per) < 3:
        unbekannt.append(status)
        return None
    hr, gr = sum(p[0] for p in per[:3]), sum(p[1] for p in per[:3])
    oben = status.upper()
    if hr != gr:
        ende = "REG"
        if (hr, gr) != (hs, gs):
            unbekannt.append(status)       # Summe der Drittel passt nicht zum Endstand
            return None
    else:
        if hs == gs:
            unbekannt.append(status)       # kein Sieger, vermutlich unvollstaendig
            return None
        if any(k in oben for k in ("N.P", "PS", "SO", "PENALTY")):
            ende = "SO"
        elif any(k in oben for k in ("N.V", "OT", "VERL")):
            ende = "OT"
        elif len(per) >= 5 or (len(per) == 4 and per[3][0] == per[3][1]):
            ende = "SO"                    # Verlaengerung torlos, also Penaltyschiessen
        elif len(per) == 4:
            ende = "OT"
        else:
            ende = "SO" if abs(hs - gs) == 1 else "OT"
            unbekannt.append("geraten: " + status)
    spiel.update(hs=hs, gs=gs, hr=hr, gr=gr, ende=ende)
    return spiel


def spielplan(saison):
    pfade = teamseiten(saison)
    alle, unbekannt = {}, []
    for p in pfade:
        h = holen(p)
        start = h.find("team-schedule__compet")
        for roh in ZEILE.findall(h[start:] if start > 0 else ""):
            s = zeile_lesen(roh, saison, unbekannt)
            if not s:
                continue
            k = s["id"] if not s["offen"] else f'{s["datum"]}_{s["heim"]}_{s["gast"]}'
            alle[k] = s
        time.sleep(0.3)
    fertig = [s for s in alle.values() if not s["offen"]]
    offen = [s for s in alle.values() if s["offen"]]
    print(f"  {saison}: {len(pfade)} Teams, {len(fertig)} Spiele gespielt, {len(offen)} offen")
    for u in unbekannt[:5]:
        print("    nicht gelesen:", u[:120])
    return fertig, offen


# ---------------------------------------------------------------- Spielseite
STAT = re.compile(r'progress-labels__title">([^<]+)</div>.*?progress-labels__value">([^<]*)</div>'
                  r'\s*<div class="progress-labels__value">([^<]*)</div>', re.S)


def spielseite(pfad):
    h = holen(pfad)
    if not h:
        return None
    werte = {}
    for t, a, b in STAT.findall(h):
        werte[text(t).lower()] = (zahl(a), zahl(b))
    return werte


def wert(werte, *namen):
    for n in namen:
        if n in werte:
            return werte[n]
    return ("", "")


# ---------------------------------------------------------------- Dateien
def vorhandene_lesen():
    if not os.path.exists(SPIELE):
        return {}
    try:
        with open(SPIELE, encoding="utf-8", newline="") as f:
            leser = csv.DictReader(f)
            if leser.fieldnames != KOPF_SPIELE:
                print("  Spaltenaufbau geaendert, baue neu auf")
                return {}
            return {z["GameId"]: [z[k] for k in KOPF_SPIELE] for z in leser}
    except Exception as e:
        print("  Vorhandene Datei nicht lesbar:", type(e).__name__)
        return {}


def schreiben(pfad, kopf, zeilen):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{pfad}: {len(zeilen)} Zeilen")


def utc(iso, uhr):
    try:
        t = datetime.strptime(f"{iso} {uhr or '19:30'}", "%Y-%m-%d %H:%M").replace(tzinfo=BERLIN)
        return t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def main():
    os.makedirs(ORDNER, exist_ok=True)
    bestand = vorhandene_lesen()
    print(f"{len(bestand)} Spiele bereits vorhanden")
    liste = saisons()
    ansetzungen, beginn = [], time.time()
    neu = fehlt = 0
    for i, saison in enumerate(liste):
        aktuell = i == len(liste) - 1
        schon = sum(1 for z in bestand.values() if z[2] == saison)
        if not aktuell and schon >= 350:
            print(f"  {saison}: abgeschlossen, {schon} Spiele im Bestand")
            continue
        fertig, offen = spielplan(saison)
        if aktuell:
            heute = date.today().isoformat()
            for s in sorted(offen, key=lambda s: (s["datum"], s["uhr"])):
                if s["datum"] >= heute:
                    ansetzungen.append([utc(s["datum"], s["uhr"]),
                                        f'{s["datum"]}_{s["heim"]}_{s["gast"]}',
                                        s["heim"], s["gast"], s["spieltag"]])
        for s in sorted(fertig, key=lambda s: s["datum"]):
            if s["id"] in bestand and bestand[s["id"]][10] != "":
                continue
            if s["id"] in bestand and time.time() - beginn > ZEITLIMIT:
                continue
            if time.time() - beginn > ZEITLIMIT:
                w = {}                     # Ergebnis schon speichern, Statistik spaeter
            else:
                w = spielseite(s["pfad"]) or {}
                time.sleep(0.4)
            sog = wert(w, "schüsse auf tor", "schüsse aufs tor", "torschüsse")
            pim = wert(w, "strafminuten")
            ges = wert(w, "schüsse gesamt")
            pp = wert(w, "powerplays")
            bul = wert(w, "bullies gewonnen")
            if sog[0] == "":
                fehlt += 1
            bestand[s["id"]] = [s["datum"], s["id"], saison, s["heim"], s["gast"],
                                s["hs"], s["gs"], s["hr"], s["gr"], s["ende"],
                                sog[0], sog[1], pim[0], pim[1], "", "", "", "",
                                s["spieltag"], ges[0], ges[1], pp[0], pp[1], bul[0], bul[1]]
            neu += 1
            if neu % 100 == 0:
                print(f"    {neu} Spielseiten gelesen")
    print(f"  {neu} Spiele ergaenzt, {fehlt} ohne Statistik (folgt beim naechsten Lauf)")

    zeilen = sorted(bestand.values(), key=lambda z: (z[2], z[0], int(z[1]) if str(z[1]).isdigit() else 0))
    if zeilen:
        schreiben(SPIELE, KOPF_SPIELE, zeilen)
    schreiben(f"{ORDNER}/del-ansetzungen.csv", KOPF_ANS, ansetzungen)


if __name__ == "__main__":
    main()
