#!/usr/bin/env python3
"""Holt NHL-Daten von der offenen Schnittstelle api-web.nhle.com.

Arbeitet ergaenzend: Bereits vorhandene Spiele werden aus der Datei
uebernommen, abgerufen wird nur, was fehlt. Der erste Lauf dauert lange,
jeder weitere nur noch Sekunden.

Erzeugt:
  daten/nhl-spiele.csv       Tore, Schuesse, Strafminuten, Torhueter
  daten/nhl-torhueter.csv    Saisonwerte der Torhueter
  daten/nhl-ansetzungen.csv  kommende Spiele
"""

import csv, json, os, time, urllib.request
from datetime import date, timedelta

WEB = "https://api-web.nhle.com/v1"
SAISONS = ["20242025", "20252026", "20262027"]
ORDNER = "daten"
SPIELE = f"{ORDNER}/nhl-spiele.csv"

KOPF_SPIELE = ["Datum","GameId","Saison","Heim","Gast",
               "HeimTore","GastTore","HeimReg","GastReg","Ende",
               "HeimSOG","GastSOG","HeimPIM","GastPIM",
               "HeimTwId","HeimTw","GastTwId","GastTw"]
KOPF_TW  = ["Id","Name","Team","Saison","Spiele","Gegentore","Schuesse"]
KOPF_ANS = ["Zeit","GameId","Heim","Gast"]


def hole(url, versuche=3, still=False):
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "linien-modell/1.0 (privates Projekt)",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if i == versuche - 1:
                if not still:
                    print("  Fehler bei", url[:90], "->", type(e).__name__)
                return None
            time.sleep(2)
    return None


def vorhandene_lesen():
    """Gibt (Zeilen, Menge der GameIds) zurueck; bei anderem Aufbau leer."""
    if not os.path.exists(SPIELE):
        return [], set()
    try:
        with open(SPIELE, encoding="utf-8", newline="") as f:
            leser = csv.DictReader(f)
            if leser.fieldnames != KOPF_SPIELE:
                print("  Spaltenaufbau hat sich geaendert, baue neu auf")
                return [], set()
            zeilen = [[z.get(k, "") for k in KOPF_SPIELE] for z in leser]
        ids = {str(z[1]) for z in zeilen}
        print(f"  {len(zeilen)} Spiele bereits vorhanden")
        return zeilen, ids
    except Exception as e:
        print("  Vorhandene Datei nicht lesbar:", type(e).__name__)
        return [], set()


def teams_holen():
    d = hole(f"{WEB}/standings/now")
    if not d:
        return []
    codes = []
    for t in d.get("standings", []):
        ab = (t.get("teamAbbrev") or {}).get("default")
        if ab and ab not in codes:
            codes.append(ab)
    return codes


def zahl(v, standard=0):
    try:
        return int(float(v))
    except Exception:
        return standard


def toi_sekunden(s):
    try:
        m, sek = str(s).split(":")
        return int(m) * 60 + int(sek)
    except Exception:
        return 0


def torhueter(seite):
    liste = seite.get("goalies") or []
    if not liste:
        return None, "", 0, 0
    bester = max(liste, key=lambda g: toi_sekunden(g.get("toi")))
    name = (bester.get("name") or {}).get("default") or ""
    gegen, schuesse = 0, 0
    roh = bester.get("saveShotsAgainst")
    if roh and "/" in str(roh):
        try:
            sv, sa = str(roh).split("/")
            schuesse = int(sa)
            gegen = int(sa) - int(sv)
        except Exception:
            pass
    if not schuesse:
        gegen = zahl(bester.get("goalsAgainst"))
    return bester.get("playerId"), name, gegen, schuesse


def spiel_ids(codes, saison):
    ids = {}
    for code in codes:
        d = hole(f"{WEB}/club-schedule-season/{code}/{saison}", still=True)
        if not d:
            continue
        for g in d.get("games", []):
            if g.get("gameType") != 2:
                continue
            if g.get("gameState") not in ("FINAL", "OFF"):
                continue
            ids[str(g.get("id"))] = g.get("gameDate", "")
        time.sleep(0.12)
    return ids


def boxscore_verarbeiten(pk, datum_, saison):
    d = hole(f"{WEB}/gamecenter/{pk}/boxscore", still=True)
    if not d:
        return None
    heim, gast = d.get("homeTeam") or {}, d.get("awayTeam") or {}
    hs, gs = heim.get("score"), gast.get("score")
    if hs is None or gs is None:
        return None
    stats = d.get("playerByGameStats") or {}
    hSeite, gSeite = stats.get("homeTeam") or {}, stats.get("awayTeam") or {}

    def pim(seite):
        summe = 0
        for gruppe in ("forwards", "defense", "goalies"):
            for p in seite.get(gruppe) or []:
                summe += zahl(p.get("pim"))
        return summe

    ende = ((d.get("gameOutcome") or {}).get("lastPeriodType")
            or (d.get("summary") or {}).get("lastPeriodType") or "REG")
    hReg, gReg = hs, gs
    if ende in ("OT", "SO"):
        if hs > gs:
            hReg = hs - 1
        elif gs > hs:
            gReg = gs - 1

    hid, hnm, _, _ = torhueter(hSeite)
    gid, gnm, _, _ = torhueter(gSeite)
    return [datum_, pk, saison,
            heim.get("abbrev", ""), gast.get("abbrev", ""),
            hs, gs, hReg, gReg, ende,
            zahl(heim.get("sog")), zahl(gast.get("sog")),
            pim(hSeite), pim(gSeite),
            hid or "", hnm, gid or "", gnm]


def torhueter_zusammenfassen(zeilen):
    """Wird aus der fertigen Spieltabelle berechnet, ohne weitere Abrufe."""
    summe = {}
    for z in zeilen:
        saison = z[2]
        for tid, tnm, team in ((z[14], z[15], z[3]), (z[16], z[17], z[4])):
            if not tid:
                continue
            k = (str(tid), str(saison))
            x = summe.setdefault(k, [tid, tnm, team, saison, 0, 0, 0])
            x[1] = tnm or x[1]
            x[4] += 1
    return list(summe.values())


def ansetzungen_holen():
    raus, gesehen = [], set()
    heute = date.today()
    for versatz in (0, 7):
        d = hole(f"{WEB}/schedule/{heute + timedelta(days=versatz)}")
        if not d:
            continue
        for tag in d.get("gameWeek", []):
            for g in tag.get("games", []):
                if g.get("gameState") in ("FINAL", "OFF"):
                    continue
                if g.get("id") in gesehen:
                    continue
                gesehen.add(g.get("id"))
                raus.append([g.get("startTimeUTC", ""), g.get("id"),
                             (g.get("homeTeam") or {}).get("abbrev", ""),
                             (g.get("awayTeam") or {}).get("abbrev", "")])
        time.sleep(0.2)
    return raus


def schreiben(pfad, kopf, zeilen):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{pfad}: {len(zeilen)} Zeilen")


def main():
    os.makedirs(ORDNER, exist_ok=True)
    spiele, bekannt = vorhandene_lesen()

    codes = teams_holen()
    print(f"{len(codes)} Mannschaften gefunden")
    if not codes:
        print("Ohne Mannschaftsliste kein Abruf, behalte den Bestand")
    else:
        neu = fehler = 0
        for saison in SAISONS:
            ids = spiel_ids(codes, saison)
            offen = {k: v for k, v in ids.items() if k not in bekannt}
            print(f"  {saison}: {len(ids)} Spiele, davon {len(offen)} neu")
            for i, (pk, dat) in enumerate(sorted(offen.items()), 1):
                try:
                    zeile = boxscore_verarbeiten(pk, dat, saison)
                except Exception:
                    zeile = None
                if zeile:
                    spiele.append(zeile)
                    bekannt.add(pk)
                    neu += 1
                else:
                    fehler += 1
                if i % 200 == 0:
                    print(f"    {i} von {len(offen)}")
                time.sleep(0.08)
        print(f"  {neu} Spiele ergaenzt, {fehler} nicht abrufbar")

    spiele.sort(key=lambda z: (str(z[2]), str(z[0]), str(z[1])))
    schreiben(SPIELE, KOPF_SPIELE, spiele)
    schreiben(f"{ORDNER}/nhl-torhueter.csv", KOPF_TW,
              torhueter_zusammenfassen(spiele))
    print("Ansetzungen holen ...")
    schreiben(f"{ORDNER}/nhl-ansetzungen.csv", KOPF_ANS, ansetzungen_holen())


if __name__ == "__main__":
    main()
