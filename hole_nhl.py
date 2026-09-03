#!/usr/bin/env python3
"""Holt NHL-Daten von der offenen Schnittstelle api-web.nhle.com.

Erzeugt:
  daten/nhl-spiele.csv       abgeschlossene Spiele mit Toren, Schuessen,
                             Strafminuten und den eingesetzten Torhuetern
  daten/nhl-torhueter.csv    Saisonwerte der Torhueter
  daten/nhl-ansetzungen.csv  kommende Spiele

Die Torzahl wird zusaetzlich ohne Verlaengerung ausgewiesen: bei einem Sieg
nach Verlaengerung oder Penaltyschiessen faellt genau ein Tor weg, das nicht
zur reguleren Spielzeit gehoert.
"""

import json, os, csv, time, urllib.request
from datetime import date, timedelta

WEB    = "https://api-web.nhle.com/v1"
SAISONS = ["20242025", "20252026", "20262027"]
ORDNER = "daten"

KOPF_SPIELE = ["Datum","GameId","Saison","Heim","Gast",
               "HeimTore","GastTore","HeimReg","GastReg","Ende",
               "HeimSOG","GastSOG","HeimPIM","GastPIM",
               "HeimTwId","HeimTw","GastTwId","GastTw"]
KOPF_TW     = ["Id","Name","Team","Saison","Spiele","Gegentore","Schuesse"]
KOPF_ANS    = ["Zeit","GameId","Heim","Gast"]


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
    """Der Torhueter mit der meisten Eiszeit gilt als Starter."""
    liste = seite.get("goalies") or []
    if not liste:
        return None, "", 0, 0
    bester = max(liste, key=lambda g: toi_sekunden(g.get("toi")))
    name = (bester.get("name") or {}).get("default") or bester.get("sweaterNumber", "")
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
            ids[g.get("id")] = g.get("gameDate", "")
        time.sleep(0.15)
    return ids


def boxscore_verarbeiten(pk, datum_, saison):
    d = hole(f"{WEB}/gamecenter/{pk}/boxscore", still=True)
    if not d:
        return None, None
    heim, gast = d.get("homeTeam") or {}, d.get("awayTeam") or {}
    hs, gs = heim.get("score"), gast.get("score")
    if hs is None or gs is None:
        return None, None
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
    # In Verlaengerung oder Penaltyschiessen faellt genau ein Siegtor
    hReg, gReg = hs, gs
    if ende in ("OT", "SO"):
        if hs > gs:
            hReg = hs - 1
        elif gs > hs:
            gReg = gs - 1

    hid, hnm, hGegen, hSch = torhueter(hSeite)
    gid, gnm, gGegen, gSch = torhueter(gSeite)

    zeile = [datum_, pk, saison,
             heim.get("abbrev", ""), gast.get("abbrev", ""),
             hs, gs, hReg, gReg, ende,
             zahl(heim.get("sog")), zahl(gast.get("sog")),
             pim(hSeite), pim(gSeite),
             hid or "", hnm, gid or "", gnm]
    tw = [(hid, hnm, heim.get("abbrev", ""), saison, hGegen, hSch),
          (gid, gnm, gast.get("abbrev", ""), saison, gGegen, gSch)]
    return zeile, tw


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
    codes = teams_holen()
    print(f"{len(codes)} Mannschaften gefunden")
    if not codes:
        print("Ohne Mannschaftsliste kein Abruf moeglich")
        return

    spiele, tw_summe = [], {}
    for saison in SAISONS:
        ids = spiel_ids(codes, saison)
        print(f"  {saison}: {len(ids)} abgeschlossene Spiele")
        n = 0
        for pk, dat in sorted(ids.items()):
            zeile, tw = boxscore_verarbeiten(pk, dat, saison)
            if not zeile:
                continue
            spiele.append(zeile)
            for tid, tnm, team, sa, gegen, sch in tw:
                if not tid:
                    continue
                k = (tid, sa)
                x = tw_summe.setdefault(k, [tid, tnm, team, sa, 0, 0, 0])
                x[1] = tnm or x[1]
                x[2] = team or x[2]
                x[4] += 1
                x[5] += gegen
                x[6] += sch
            n += 1
            if n % 200 == 0:
                print(f"    {n} von {len(ids)} verarbeitet")
            time.sleep(0.08)

    schreiben(f"{ORDNER}/nhl-spiele.csv", KOPF_SPIELE, spiele)
    schreiben(f"{ORDNER}/nhl-torhueter.csv", KOPF_TW, list(tw_summe.values()))
    print("Ansetzungen holen ...")
    schreiben(f"{ORDNER}/nhl-ansetzungen.csv", KOPF_ANS, ansetzungen_holen())


if __name__ == "__main__":
    main()
