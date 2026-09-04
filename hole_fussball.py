#!/usr/bin/env python3
"""Holt die Ligadateien und die Ansetzungen von football-data.co.uk.

Erzeugt daten/<Saison>-<Liga>.csv sowie daten/fixtures.csv,
jeweils von Windows-1252 nach UTF-8 umgewandelt.

Hinweis zu den Ansetzungen: football-data traegt die Wochenendpartien mitsamt
Quoten erst Freitagnachmittag ein. Ein Versuch, die Paarungen frueher bei ESPN
zu holen, scheiterte an HTTP 403 - die Schnittstelle sperrt Anfragen aus
Rechenzentren. Deshalb bleibt es bei dieser einen Quelle.
"""

import os, time, urllib.request

SAISONS = ["2425", "2526", "2627"]      # im Sommer die neue anhaengen
LIGEN = ["E0", "E1", "E2", "E3", "EC",
         "SC0", "SC1", "SC2", "SC3",
         "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2",
         "N1", "B1", "P1", "T1", "G1"]
BASIS = "https://www.football-data.co.uk"
ORDNER = "daten"


def hole(url, versuche=3):
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "linien-modell/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                if r.status != 200:
                    return None
                return r.read()
        except Exception:
            if i == versuche - 1:
                return None
            time.sleep(2)
    return None


def schreiben(pfad, rohdaten):
    """Windows-1252 nach UTF-8; unbekannte Zeichen werden verworfen."""
    text = rohdaten.decode("cp1252", errors="ignore")
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return text.count("\n")


def main():
    os.makedirs(ORDNER, exist_ok=True)
    ok = fehlt = 0

    for saison in SAISONS:
        for liga in LIGEN:
            url = f"{BASIS}/mmz4281/{saison}/{liga}.csv"
            roh = hole(url)
            ziel = f"{ORDNER}/{saison}-{liga}.csv"
            if roh and len(roh) > 200:
                zeilen = schreiben(ziel, roh)
                print(f"ok    {saison}-{liga}  {zeilen} Zeilen")
                ok += 1
            else:
                print(f"FEHLT {saison}-{liga}")
                fehlt += 1
            time.sleep(0.2)

    roh = hole(f"{BASIS}/fixtures.csv")
    if roh and len(roh) > 100:
        zeilen = schreiben(f"{ORDNER}/fixtures.csv", roh)
        print(f"Ansetzungen ok, {zeilen} Zeilen")
    else:
        print("Ansetzungen nicht erreichbar")

    print(f"\nFertig: {ok} Dateien geholt, {fehlt} nicht vorhanden.")


if __name__ == "__main__":
    main()
