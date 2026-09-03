#!/usr/bin/env python3
"""Holt NFL-Daten aus den nflverse-Releases.

Quelle: https://github.com/nflverse/nflverse-data/releases
Die Dateinamen haben sich ueber die Jahre geaendert, deshalb werden mehrere
Kandidaten probiert und der erste funktionierende genommen.

Erzeugt:
  daten/nfl-spieler.csv      Wochenwerte je Spieler: Volumen, Yards, Touchdowns
  daten/nfl-ansetzungen.csv  kommende Partien
"""

import csv, gzip, io, os, time, urllib.error, urllib.request

SAISONS = [2024, 2025, 2026]
ORDNER = "daten"
BASIS = "https://github.com/nflverse/nflverse-data/releases/download"

KOPF_SP = ["Saison","Woche","SpielerId","Name","Position","Team","Gegner",
           "Att","PassYds","PassTD","Int",
           "Carries","RushYds","RushTD",
           "Targets","Rec","RecYds","RecTD"]
KOPF_AN = ["Datum","Zeit","Saison","Woche","Heim","Gast"]
KOPF_KA = ["SpielerId","Name","Position","Team","Status","Saison"]


def hole(url, still=False):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "linien-modell/1.0 (privates Projekt)",
            "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=90) as r:
            roh = r.read()
    except urllib.error.HTTPError as e:
        if not still:
            print(f"    {url.split('/')[-1]}: HTTP {e.code}")
        return None
    except Exception as e:
        if not still:
            print(f"    {url.split('/')[-1]}: {type(e).__name__}")
        return None
    if roh[:2] == b"\x1f\x8b":
        try:
            roh = gzip.decompress(roh)
        except Exception:
            return None
    return roh


def csv_lesen(roh):
    for kod in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return list(csv.DictReader(io.StringIO(roh.decode(kod))))
        except Exception:
            continue
    return []


def erste_treffer(kandidaten):
    """Probiert Adressen der Reihe nach und gibt die erste brauchbare zurueck."""
    for url in kandidaten:
        roh = hole(url, still=True)
        if roh and len(roh) > 2000:
            zeilen = csv_lesen(roh)
            if zeilen:
                print(f"    ok {url.split('/')[-1]}  {len(zeilen)} Zeilen")
                return zeilen
        print(f"    fehlt {url.split('/')[-1]}")
    return []


def wert(z, *namen):
    for n in namen:
        if n in z and str(z[n]).strip() not in ("", "NA", "None"):
            return z[n]
    return ""


def zahl(v):
    try:
        return int(round(float(v)))
    except Exception:
        return 0


def spieler_holen():
    raus = []
    for jahr in SAISONS:
        print(f"  Saison {jahr}")
        zeilen = erste_treffer([
            f"{BASIS}/player_stats/player_stats_{jahr}.csv",
            f"{BASIS}/player_stats/stats_player_week_{jahr}.csv",
            f"{BASIS}/stats_player/stats_player_week_{jahr}.csv",
            f"{BASIS}/player_stats/player_stats_{jahr}.csv.gz",
            f"{BASIS}/stats_player/stats_player_week_{jahr}.csv.gz",
        ])
        anz = 0
        for z in zeilen:
            typ = str(wert(z, "season_type")).upper()
            if typ and typ != "REG":
                continue
            team = wert(z, "recent_team", "team")
            name = wert(z, "player_display_name", "player_name", "name")
            if not team or not name:
                continue
            raus.append([
                jahr, zahl(wert(z, "week")),
                wert(z, "player_id", "gsis_id"), name,
                wert(z, "position", "position_group"),
                team, wert(z, "opponent_team", "opponent"),
                zahl(wert(z, "attempts")), zahl(wert(z, "passing_yards")),
                zahl(wert(z, "passing_tds")), zahl(wert(z, "interceptions")),
                zahl(wert(z, "carries")), zahl(wert(z, "rushing_yards")),
                zahl(wert(z, "rushing_tds")),
                zahl(wert(z, "targets")), zahl(wert(z, "receptions")),
                zahl(wert(z, "receiving_yards")), zahl(wert(z, "receiving_tds")),
            ])
            anz += 1
        print(f"    {anz} verwertbare Wochenzeilen")
        time.sleep(0.3)
    return raus


def ansetzungen_holen():
    zeilen = erste_treffer([
        f"{BASIS}/schedules/games.csv",
        f"{BASIS}/schedules/schedules.csv",
        f"{BASIS}/schedules/games.csv.gz",
    ])
    raus = []
    for z in zeilen:
        if zahl(wert(z, "season")) not in SAISONS:
            continue
        if str(wert(z, "game_type")).upper() not in ("REG", ""):
            continue
        # nur Partien ohne Endstand gelten als kommend
        if str(wert(z, "home_score")).strip() not in ("", "NA", "None"):
            continue
        heim, gast = wert(z, "home_team"), wert(z, "away_team")
        if not heim or not gast:
            continue
        raus.append([wert(z, "gameday", "game_date"), wert(z, "gametime"),
                     zahl(wert(z, "season")), zahl(wert(z, "week")), heim, gast])
    raus.sort(key=lambda r: (str(r[0]), str(r[1])))
    return raus


def kader_holen():
    """Aktuelle Zugehoerigkeit; ohne das stehen Spieler beim alten Team."""
    jahr = max(SAISONS)
    zeilen = erste_treffer([
        f"{BASIS}/rosters/roster_{jahr}.csv",
        f"{BASIS}/weekly_rosters/roster_weekly_{jahr}.csv",
        f"{BASIS}/rosters/roster_weekly_{jahr}.csv",
        f"{BASIS}/rosters/roster_{jahr}.csv.gz",
    ])
    if not zeilen:
        # Fallback: Vorsaison, besser als gar nichts
        jahr = max(SAISONS) - 1
        print(f"    Rueckfall auf Saison {jahr}")
        zeilen = erste_treffer([
            f"{BASIS}/rosters/roster_{jahr}.csv",
            f"{BASIS}/weekly_rosters/roster_weekly_{jahr}.csv",
        ])
    neuste = {}
    for z in zeilen:
        pid = wert(z, "gsis_id", "player_id", "pfr_id")
        team = wert(z, "team", "recent_team", "club_code")
        if not pid or not team:
            continue
        woche = zahl(wert(z, "week"))
        alt = neuste.get(pid)
        if alt and alt[0] >= woche:
            continue
        neuste[pid] = (woche, [
            pid,
            wert(z, "full_name", "player_name", "football_name"),
            wert(z, "position", "depth_chart_position"),
            team,
            wert(z, "status") or "ACT",
            jahr,
        ])
    return [v[1] for v in neuste.values()]


def schreiben(pfad, kopf, zeilen):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{pfad}: {len(zeilen)} Zeilen")


def main():
    os.makedirs(ORDNER, exist_ok=True)
    print("Spielerwochen holen ...")
    schreiben(f"{ORDNER}/nfl-spieler.csv", KOPF_SP, spieler_holen())
    print("Kader holen ...")
    schreiben(f"{ORDNER}/nfl-kader.csv", KOPF_KA, kader_holen())
    print("Ansetzungen holen ...")
    schreiben(f"{ORDNER}/nfl-ansetzungen.csv", KOPF_AN, ansetzungen_holen())


if __name__ == "__main__":
    main()
