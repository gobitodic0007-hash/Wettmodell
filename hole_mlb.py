#!/usr/bin/env python3
"""Holt MLB-Daten von statsapi.mlb.com.

Erzeugt:
  daten/mlb-spiele.csv       abgeschlossene Spiele mit F5-Runs und Startern
  daten/mlb-pitcher.csv      Saisonwerte der Starter
  daten/mlb-starts.csv       je Start: Batters Faced, Strikeouts, Innings
  daten/mlb-teams.csv        Strikeout-Anfaelligkeit der Offensiven
  daten/mlb-ansetzungen.csv  kommende Spiele mit angekuendigten Startern

Listet ausserdem auf, welche Ligen die Schnittstelle fuehrt.
"""

import json, os, csv, time, urllib.request
from datetime import date, timedelta

BASIS   = "https://statsapi.mlb.com/api/v1"
SAISONS = [2024, 2025, 2026]
LOG_SAISONS = [2025, 2026]      # Startprotokolle nur fuer die juengsten Jahre
MIN_IP  = 20                    # ab wie vielen Innings ein Werfer protokolliert wird
ORDNER  = "daten"

KOPF_SPIELE = ["Datum","GamePk","Park","Heim","Gast",
               "HeimF5","GastF5","HeimI1","GastI1","HeimR","GastR",
               "HeimHits","GastHits","HeimHitsF5","GastHitsF5",
               "HeimStarterId","HeimStarter","GastStarterId","GastStarter"]
KOPF_PITCH  = ["Id","Name","Saison","IP","R","ER","SO","BB","HBP","HR","BF","GS"]
KOPF_STARTS = ["Datum","PitcherId","Gegner","BF","SO","IP","Heim"]
KOPF_TEAMS  = ["Team","Saison","PA","SO"]
KOPF_ANS    = ["Zeit","GamePk","Park","Heim","Gast",
               "HeimStarterId","HeimStarter","GastStarterId","GastStarter"]


SPIELE = f"{ORDNER}/mlb-spiele.csv"


def vorhandene_lesen(pfad, kopf):
    """Bestand uebernehmen; bei geaendertem Aufbau von vorn beginnen."""
    if not os.path.exists(pfad):
        return []
    try:
        with open(pfad, encoding="utf-8", newline="") as f:
            leser = csv.DictReader(f)
            if leser.fieldnames != kopf:
                print(f"  {pfad}: Aufbau geaendert, baue neu auf")
                return []
            return [[z.get(k, "") for k in kopf] for z in leser]
    except Exception as e:
        print(f"  {pfad} nicht lesbar:", type(e).__name__)
        return []


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


def hits(halb):
    return (halb or {}).get("hits") or 0


def ligen_auflisten():
    d = hole(f"{BASIS}/sports")
    if not d:
        print("  Ligenliste nicht abrufbar")
        return
    for s in d.get("sports", []):
        print(f"  sportId {s.get('id')}: {s.get('name')} ({s.get('code')})")


def starter_aus_boxscore(pk):
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


def spiele_holen(bekannt):
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
                    if str(g.get("gamePk")) in bekannt:
                        continue
                    ls = g.get("linescore", {})
                    inn = ls.get("innings", [])
                    if len(inn) < 5:
                        continue
                    heim, gast = g["teams"]["home"], g["teams"]["away"]
                    lsT = ls.get("teams", {})
                    hHit = (lsT.get("home") or {}).get("hits")
                    gHit = (lsT.get("away") or {}).get("hits")
                    if hHit is None:
                        hHit = sum(hits(i.get("home")) for i in inn) or ""
                    if gHit is None:
                        gHit = sum(hits(i.get("away")) for i in inn) or ""
                    hHit5 = sum(hits(i.get("home")) for i in inn[:5])
                    gHit5 = sum(hits(i.get("away")) for i in inn[:5])
                    # Stehen keine Hits je Inning bereit, bleibt die Spalte leer
                    if hHit5 == 0 and gHit5 == 0:
                        hHit5 = gHit5 = ""
                    hp = heim.get("probablePitcher") or {}
                    gp = gast.get("probablePitcher") or {}
                    hid, hnm = hp.get("id"), hp.get("fullName", "")
                    gid, gnm = gp.get("id"), gp.get("fullName", "")
                    if not hid or not gid:
                        h2, hn2, g2, gn2 = starter_aus_boxscore(g["gamePk"])
                        hid, hnm = hid or h2, hnm or hn2
                        gid, gnm = gid or g2, gnm or gn2
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
                        hHit, gHit, hHit5, gHit5,
                        hid or "", hnm, gid or "", gnm,
                    ])
                    anz += 1
            print(f"  {jahr}-{monat:02d}: {anz} neue Spiele")
            time.sleep(0.3)
    return zeilen, pitcher_ids


def pitcher_holen(ids):
    zeilen, viel = [], set()
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
        ip = ip_zahl(st.get("inningsPitched", 0))
        zeilen.append([
            pid, p.get("fullName", ""), jahr, round(ip, 2),
            st.get("runs", 0), st.get("earnedRuns", 0),
            st.get("strikeOuts", 0), st.get("baseOnBalls", 0),
            st.get("hitByPitch", 0), st.get("homeRuns", 0),
            st.get("battersFaced", 0), st.get("gamesStarted", 0),
        ])
        if ip >= MIN_IP and jahr in LOG_SAISONS:
            viel.add((pid, jahr))
        if n % 50 == 0:
            print(f"  {n} von {len(ids)} Pitchern")
        time.sleep(0.12)
    return zeilen, viel


def starts_holen(viel, behalten):
    """Je Start: Batters Faced, Strikeouts, Innings, Gegner.
    Aeltere Saisons werden aus dem Bestand uebernommen."""
    zeilen = list(behalten)
    for n, (pid, jahr) in enumerate(sorted(viel), 1):
        url = (f"{BASIS}/people/{pid}/stats"
               f"?stats=gameLog&group=pitching&season={jahr}")
        d = hole(url)
        if not d:
            continue
        for block in d.get("stats", []):
            for sp in block.get("splits", []):
                st = sp.get("stat", {})
                if not st.get("gamesStarted"):
                    continue
                bf = st.get("battersFaced")
                if not bf:
                    continue
                zeilen.append([
                    sp.get("date", ""), pid,
                    (sp.get("opponent") or {}).get("name", ""),
                    bf, st.get("strikeOuts", 0),
                    round(ip_zahl(st.get("inningsPitched", 0)), 2),
                    1 if sp.get("isHome") else 0,
                ])
        if n % 50 == 0:
            print(f"  {n} von {len(viel)} Startprotokollen")
        time.sleep(0.12)
    return zeilen


def teams_holen():
    """Strikeout-Anfaelligkeit der Offensiven."""
    zeilen = []
    for jahr in LOG_SAISONS:
        url = (f"{BASIS}/teams/stats?stats=season&group=hitting"
               f"&season={jahr}&sportIds=1")
        d = hole(url)
        if not d:
            continue
        for block in d.get("stats", []):
            for sp in block.get("splits", []):
                st = sp.get("stat", {})
                team = (sp.get("team") or {}).get("name", "")
                if not team:
                    continue
                zeilen.append([team, jahr,
                               st.get("plateAppearances", 0),
                               st.get("strikeOuts", 0)])
        time.sleep(0.3)
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
    laufend = max(SAISONS)

    alt_spiele = vorhandene_lesen(SPIELE, KOPF_SPIELE)
    bekannt = {str(z[1]) for z in alt_spiele}
    print(f"{len(alt_spiele)} Spiele bereits vorhanden")

    print("Spiele holen ...")
    neue, ids = spiele_holen(bekannt)
    spiele = alt_spiele + neue
    spiele.sort(key=lambda z: (str(z[0]), str(z[1])))
    print(f"  {len(neue)} Spiele ergaenzt")
    schreiben(SPIELE, KOPF_SPIELE, spiele)

    # Werfer der laufenden Saison immer neu holen, damit die Werte aktuell bleiben
    for z in spiele:
        jahr = str(z[0])[:4]
        if not jahr.isdigit() or int(jahr) != laufend:
            continue
        for spalte in (15, 17):          # HeimStarterId, GastStarterId
            pid = str(z[spalte]).strip()
            if pid:
                try:
                    ids.add((int(float(pid)), laufend))
                except ValueError:
                    pass

    alt_pitcher = vorhandene_lesen(f"{ORDNER}/mlb-pitcher.csv", KOPF_PITCH)
    def paar(z):
        try:
            return (int(float(z[0])), int(float(z[2])))
        except Exception:
            return None
    behalten_p = [z for z in alt_pitcher
                  if str(z[2]) != str(laufend) and paar(z) not in ids]
    print(f"Pitcher holen ({len(ids)}), {len(behalten_p)} aus dem Bestand ...")
    pitcher, viel = pitcher_holen(ids)
    schreiben(f"{ORDNER}/mlb-pitcher.csv", KOPF_PITCH, behalten_p + pitcher)

    alt_starts = vorhandene_lesen(f"{ORDNER}/mlb-starts.csv", KOPF_STARTS)
    behalten_s = [z for z in alt_starts
                  if not str(z[0]).startswith(str(laufend))]
    viel_akt = {(p, j) for (p, j) in viel if j == laufend}
    print(f"Startprotokolle holen ({len(viel_akt)}), "
          f"{len(behalten_s)} aus dem Bestand ...")
    schreiben(f"{ORDNER}/mlb-starts.csv", KOPF_STARTS,
              starts_holen(viel_akt, behalten_s))

    print("Offensivwerte holen ...")
    schreiben(f"{ORDNER}/mlb-teams.csv", KOPF_TEAMS, teams_holen())

    print("Ansetzungen holen ...")
    schreiben(f"{ORDNER}/mlb-ansetzungen.csv", KOPF_ANS, ansetzungen_holen())


if __name__ == "__main__":
    main()
