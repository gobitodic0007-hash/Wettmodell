#!/usr/bin/env python3
"""Holt MLB-Daten von statsapi.mlb.com und legt sie als CSV im Ordner daten ab.

Erzeugt:
  daten/mlb-spiele.csv       abgeschlossene Spiele mit F5-Runs und Startern
  daten/mlb-pitcher.csv      Saisonwerte der Starter
  daten/mlb-ansetzungen.csv  kommende Spiele mit angekuendigten Startern
"""

import json, os, csv, time, urllib.request
from datetime import date, timedelta

BASIS   = "https://statsapi.mlb.com/api/v1"
SAISONS = [2024, 2025, 2026]        # im Frühjahr die neue Saison anhängen
ORDNER  = "daten"

KOPF_SPIELE = ["Datum","GamePk","Park","Heim","Gast",
               "HeimF5","GastF5","HeimI1","GastI1","HeimR","GastR",
               "HeimStarterId","HeimStarter","GastStarterId","GastStarter"]
KOPF_PITCH  = ["Id","Name","Saison","IP","R","ER","SO","BB","HBP","HR","BF"]
KOPF_ANS    = ["Zeit","GamePk","Park","Heim","Gast",
               "HeimStarterId","HeimStarter","GastStarterId","GastStarter"]


def hole(url, versuche=3):
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "linien-modell/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if i == versuche - 1:
                print("  Fehler bei", url[:90], "->", e)
                return None
            time.sleep(3)
    return None


def ip_zahl(s):
    """MLB schreibt Innings als 145.2 und meint 145 und zwei Drittel."""
    try:
        ganz, rest = str(s).split(".")
        return int(ganz) + int(rest) / 3.0
    except Exception:
        try:
            return float(s)
        except Exception:
            return 0.0


def runs(halb):
    return (halb or {}).get("runs") or 0


def starter_aus_boxscore(pk):
    """Nur nötig, wenn im Spielplan kein Pitcher hinterlegt ist."""
    d = hole(f"{BASIS}/game/{pk}/boxscore")
    if not d:
        return (None, "", None, "")
    aus = []
    for seite in ("home", "away"):
        t = d.get("teams", {}).get(seite, {})
        liste = t.get("pitchers") or []
        if not liste:
            aus += [None, ""]
            continue
        pid = liste[0]
        sp = t.get("players", {}).get(f"ID{pid}", {})
        aus += [pid, sp.get("person", {}).get("fullName", "")]
    return tuple(aus)


def spiele_holen():
    zeilen, pitcher_ids = [], set()
    for jahr in SAISONS:
        for monat in range(3, 12):
            start = date(jahr, monat, 1)
            ende  = (date(jahr, monat + 1, 1) - timedelta(days=1)) if monat < 12 \
                    else date(jahr, 12, 31)
            if start > date.today():
                continue
            url = (f"{BASIS}/schedule?sportId=1&gameType=R"
                   f"&startDate={start}&endDate={ende}"
                   f"&hydrate=linescore,probablePitcher,venue")
            d = hole(url)
            if not d:
                continue
            anz = 0
            for tag in d.get("dates", []):
                for g in tag.get("games", []):
                    if g.get("status", {}).get("abstractGameState") != "Final":
                        continue
                    inn = g.get("linescore", {}).get("innings", [])
                    if len(inn) < 5:          # Abbruch oder verkuerztes Spiel
                        continue
                    heim = g["teams"]["home"]
                    gast = g["teams"]["away"]

                    hp = heim.get("probablePitcher") or {}
                    gp = gast.get("probablePitcher") or {}
                    hid, hnm = hp.get("id"), hp.get("fullName", "")
                    gid, gnm = gp.get("id"), gp.get("fullName", "")
                    if not hid or not gid:
                        hid2, hnm2, gid2, gnm2 = starter_aus_boxscore(g["gamePk"])
                        hid, hnm = hid or hid2, hnm or hnm2
                        gid, gnm = gid or gid2, gnm or gnm2
                        time.sleep(0.1)

                    if hid: pitcher_ids.add((hid, jahr))
                    if gid: pitcher_ids.add((gid, jahr))

                    zeilen.append([
                        g.get("officialDate", ""), g["gamePk"],
                        g.get("venue", {}).get("name", ""),
                        heim["team"]["name"], gast["team"]["name"],
                        sum(runs(i.get("home")) for i in inn[:5]),
                        sum(runs(i.get("away")) for i in inn[:5]),
                        runs(inn[0].get("home")), runs(inn[0].get("away")),
                        heim.get("score", ""), gast.get("score", ""),
                        hid or "", hnm, gid or "", gnm,
                    ])
                    anz += 1
            print(f"  {jahr}-{monat:02d}: {anz} Spiele")
            time.sleep(0.3)
    return zeilen, pitcher_ids


def pitcher_holen(ids):
    zeilen = []
    for n, (pid, jahr) in enumerate(sorted(ids), 1):
        url = (f"{BASIS}/people/{pid}"
               f"?hydrate=stats(group=[pitching],type=[season],season={jahr})")
        d = hole(url)
        if not d or not d.get("people"):
            continue
        p = d["people"][0]
        st = None
        for block in p.get("stats", []):
            for split in block.get("splits", []):
                st = split.get("stat")
        if not st:
            continue
        zeilen.append([
            pid, p.get("fullName", ""), jahr,
            round(ip_zahl(st.get("inningsPitched", 0)), 2),
            st.get("runs", 0), st.get("earnedRuns", 0),
            st.get("strikeOuts", 0), st.get("baseOnBalls", 0),
            st.get("hitByPitch", 0), st.get("homeRuns", 0),
            st.get("battersFaced", 0),
        ])
        if n % 50 == 0:
            print(f"  {n} von {len(ids)} Pitchern")
        time.sleep(0.12)
    return zeilen


def ansetzungen_holen():
    heute = date.today()
    url = (f"{BASIS}/schedule?sportId=1&gameType=R"
           f"&startDate={heute}&endDate={heute + timedelta(days=8)}"
           f"&hydrate=probablePitcher,venue")
    d = hole(url)
    zeilen = []
    if not d:
        return zeilen
    for tag in d.get("dates", []):
        for g in tag.get("games", []):
            if g.get("status", {}).get("abstractGameState") == "Final":
                continue
            heim, gast = g["teams"]["home"], g["teams"]["away"]
            hp = heim.get("probablePitcher") or {}
            gp = gast.get("probablePitcher") or {}
            zeilen.append([
                g.get("gameDate", ""), g["gamePk"],
                g.get("venue", {}).get("name", ""),
                heim["team"]["name"], gast["team"]["name"],
                hp.get("id", ""), hp.get("fullName", ""),
                gp.get("id", ""), gp.get("fullName", ""),
            ])
    return zeilen


def schreiben(pfad, kopf, zeilen):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{pfad}: {len(zeilen)} Zeilen")


def main():
    os.makedirs(ORDNER, exist_ok=True)
    print("Spiele holen ...")
    spiele, ids = spiele_holen()
    schreiben(f"{ORDNER}/mlb-spiele.csv", KOPF_SPIELE, spiele)

    print(f"Pitcher holen ({len(ids)}) ...")
    schreiben(f"{ORDNER}/mlb-pitcher.csv", KOPF_PITCH, pitcher_holen(ids))

    print("Ansetzungen holen ...")
    schreiben(f"{ORDNER}/mlb-ansetzungen.csv", KOPF_ANS, ansetzungen_holen())


if __name__ == "__main__":
    main()
