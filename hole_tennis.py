#!/usr/bin/env python3
"""Holt Tennisdaten.

Ergebnisse und Aufschlagstatistiken von Jeff Sackmanns Repos:
  https://github.com/JeffSackmann/tennis_atp
  https://github.com/JeffSackmann/tennis_wta
  Lizenz: Creative Commons BY-NC-SA. Namensnennung gehoert in die README.

Der Zweigname wird zur Laufzeit ermittelt, weil er sich geaendert hat.
Ansetzungen als Versuch ueber die offene Scoreboard-Schnittstelle von ESPN.

Erzeugt:
  daten/tennis-atp.csv
  daten/tennis-wta.csv
  daten/tennis-ansetzungen.csv
"""

import csv, io, json, os, time, urllib.error, urllib.request

JAHRE = [2024, 2025, 2026]
ORDNER = "daten"
ZWEIGE = ["master", "main"]

REPOS = {
    "atp": ("tennis_atp",
            ["atp_matches_{j}.csv",
             "atp_matches_qual_chall_{j}.csv",
             "atp_matches_futures_{j}.csv"]),
    "wta": ("tennis_wta",
            ["wta_matches_{j}.csv",
             "wta_matches_qual_itf_{j}.csv",
             "wta_matches_itf_{j}.csv"]),
}

KOPF = ["Datum","Turnier","Belag","Ebene","BestOf","Runde",
        "SiegerId","Sieger","VerliererId","Verlierer",
        "S_svpt","S_spw","V_svpt","V_spw","S_rank","V_rank"]


def hole(url, versuche=2):
    """Gibt (daten, hinweis) zurueck. daten ist None, wenn es nicht klappte."""
    letzter = "unbekannt"
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; linien-modell/1.0)",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(), "ok"
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except Exception as e:
            letzter = type(e).__name__
            if i < versuche - 1:
                time.sleep(2)
    return None, letzter


def zweig_finden(repo):
    """Probiert die bekannten Zweignamen und nimmt den ersten, der antwortet."""
    for zweig in ZWEIGE:
        url = f"https://raw.githubusercontent.com/JeffSackmann/{repo}/{zweig}/README.md"
        daten, hinweis = hole(url)
        if daten:
            print(f"  Zweig gefunden: {zweig}")
            return zweig
        print(f"  Zweig {zweig}: {hinweis}")
    return None


def zahl(v):
    try:
        return int(float(v))
    except Exception:
        return None


def datei_verarbeiten(rohdaten):
    text = rohdaten.decode("utf-8", errors="replace")
    leser = csv.DictReader(io.StringIO(text))
    raus = []
    for z in leser:
        s_svpt = zahl(z.get("w_svpt"))
        v_svpt = zahl(z.get("l_svpt"))
        if not s_svpt or not v_svpt:
            continue
        s_1 = zahl(z.get("w_1stWon")) or 0
        s_2 = zahl(z.get("w_2ndWon")) or 0
        v_1 = zahl(z.get("l_1stWon")) or 0
        v_2 = zahl(z.get("l_2ndWon")) or 0
        if s_1 + s_2 == 0 and v_1 + v_2 == 0:
            continue
        raus.append([
            z.get("tourney_date",""), z.get("tourney_name",""),
            z.get("surface",""), z.get("tourney_level",""),
            z.get("best_of",""), z.get("round",""),
            z.get("winner_id",""), z.get("winner_name",""),
            z.get("loser_id",""),  z.get("loser_name",""),
            s_svpt, s_1 + s_2, v_svpt, v_1 + v_2,
            z.get("winner_rank",""), z.get("loser_rank",""),
        ])
    return raus


def tour_holen(tour):
    repo, muster = REPOS[tour]
    zweig = zweig_finden(repo)
    if not zweig:
        print(f"  {repo}: kein Zweig erreichbar, ueberspringe")
        return []
    basis = f"https://raw.githubusercontent.com/JeffSackmann/{repo}/{zweig}/"
    alle = []
    for jahr in JAHRE:
        for m in muster:
            name = m.format(j=jahr)
            roh, hinweis = hole(basis + name)
            if not roh or len(roh) < 200:
                print(f"  fehlt {name}  ({hinweis})")
                continue
            zeilen = datei_verarbeiten(roh)
            alle += zeilen
            print(f"  ok    {name}  {len(zeilen)} verwertbare Partien")
            time.sleep(0.2)
    return alle


def ansetzungen_holen():
    raus = []
    for tour in ("atp", "wta"):
        url = (f"https://site.api.espn.com/apis/site/v2/sports/tennis/"
               f"{tour}/scoreboard")
        roh, hinweis = hole(url)
        if not roh:
            print(f"  ESPN {tour}: {hinweis}")
            continue
        try:
            d = json.loads(roh.decode("utf-8", errors="replace"))
        except Exception:
            print(f"  ESPN {tour}: Antwort war kein JSON")
            continue
        anz = 0
        for ev in d.get("events", []):
            turnier = ev.get("name", "")
            for gr in ev.get("groupings", []):
                for wett in gr.get("competitions", []):
                    zust = (wett.get("status", {})
                                .get("type", {}).get("state", ""))
                    if zust == "post":
                        continue
                    leute = wett.get("competitors", [])
                    if len(leute) != 2:
                        continue
                    namen = []
                    for k in leute:
                        a = k.get("athlete") or {}
                        namen.append(a.get("displayName") or a.get("shortName") or "")
                    if not all(namen):
                        continue
                    raus.append([
                        tour.upper(), wett.get("date",""), turnier, "",
                        wett.get("format",{}).get("bestOf",""),
                        gr.get("grouping",{}).get("shortName",""),
                        namen[0], namen[1],
                    ])
                    anz += 1
        print(f"  ESPN {tour}: {anz} kommende Partien")
    return raus


def schreiben(pfad, kopf, zeilen):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{pfad}: {len(zeilen)} Zeilen")


def main():
    os.makedirs(ORDNER, exist_ok=True)
    for tour in ("atp", "wta"):
        print(f"{tour.upper()} holen ...")
        schreiben(f"{ORDNER}/tennis-{tour}.csv", KOPF, tour_holen(tour))

    print("Ansetzungen versuchen ...")
    schreiben(f"{ORDNER}/tennis-ansetzungen.csv",
              ["Tour","Zeit","Turnier","Belag","BestOf","Runde","Spieler1","Spieler2"],
              ansetzungen_holen())


if __name__ == "__main__":
    main()
