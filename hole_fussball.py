#!/usr/bin/env python3
"""Holt die Ligadateien und die Ansetzungen von football-data.co.uk.

Ersetzt den frueheren Bash-Block. Erzeugt daten/<Saison>-<Liga>.csv
sowie daten/fixtures.csv, jeweils von Windows-1252 nach UTF-8 umgewandelt.
"""

import csv, json, os, time, unicodedata, urllib.request

SAISONS = ["2425", "2526", "2627"]      # im Sommer die neue anhaengen
LIGEN = ["E0", "E1", "E2", "E3", "EC",
         "SC0", "SC1", "SC2", "SC3",
         "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2",
         "N1", "B1", "P1", "T1", "G1"]
BASIS = "https://www.football-data.co.uk"
ORDNER = "daten"

# Die Ansetzungsdatei von football-data traegt Quoten erst ab Freitagnachmittag.
# Die Paarungen selbst stehen laengst fest; die holen wir frueher bei ESPN.
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_LIGEN = {
    "E0":"eng.1","E1":"eng.2","E2":"eng.3","E3":"eng.4","EC":"eng.5",
    "SC0":"sco.1","SC1":"sco.2","SC2":"sco.3","SC3":"sco.4",
    "D1":"ger.1","D2":"ger.2","I1":"ita.1","I2":"ita.2",
    "SP1":"esp.1","SP2":"esp.2","F1":"fra.1","F2":"fra.2",
    "N1":"ned.1","B1":"bel.1","P1":"por.1","T1":"tur.1","G1":"gre.1",
}
VORLAUF_TAGE = 9

WEGWERF = {"fc","afc","cf","sc","ac","ss","as","us","ud","cd","sd","sv","tsv",
           "vfl","vfb","bsc","bv","spvgg","kv","rc","sk","fk","if","aek",
           "club","calcio","de","of","the","1","04","05","06","07","08","09"}


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


def normal(name):
    """Namen vergleichbar machen: ohne Akzente, ohne Vereinskuerzel."""
    t = unicodedata.normalize("NFKD", str(name).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for zeichen in ".-'&/":
        t = t.replace(zeichen, " ")
    teile = [w for w in t.split() if w and w not in WEGWERF]
    return teile


def aehnlichkeit(a, b):
    """Anteil gemeinsamer Wortanfaenge, beidseitig gewichtet."""
    if not a or not b:
        return 0.0
    treffer = 0
    for w in a:
        for v in b:
            if w == v or (len(w) >= 4 and len(v) >= 4
                          and (w.startswith(v[:4]) or v.startswith(w[:4]))):
                treffer += 1
                break
    return treffer / max(len(a), len(b))


def teams_aus_datei(liga):
    """Schreibweisen, wie football-data sie verwendet."""
    namen = set()
    for saison in SAISONS:
        pfad = f"{ORDNER}/{saison}-{liga}.csv"
        if not os.path.exists(pfad):
            continue
        try:
            with open(pfad, encoding="utf-8", newline="") as f:
                for z in csv.DictReader(f):
                    for k in ("HomeTeam", "AwayTeam"):
                        if z.get(k):
                            namen.add(z[k].strip())
        except Exception:
            continue
    return sorted(namen)


def espn_holen(slug, tag):
    url = f"{ESPN}/{slug}/scoreboard?dates={tag}"
    roh = hole(url)
    if not roh:
        return []
    try:
        d = json.loads(roh.decode("utf-8", errors="replace"))
    except Exception:
        return []
    raus = []
    for ev in d.get("events", []):
        zust = ((ev.get("status") or {}).get("type") or {}).get("state", "")
        if zust == "post":
            continue
        for wett in ev.get("competitions", []):
            leute = wett.get("competitors", [])
            if len(leute) != 2:
                continue
            heim = gast = None
            for k in leute:
                t = (k.get("team") or {})
                name = t.get("displayName") or t.get("name") or ""
                if k.get("homeAway") == "home":
                    heim = name
                else:
                    gast = name
            if heim and gast:
                raus.append((wett.get("date", ""), heim, gast))
    return raus


def fruehe_ansetzungen():
    """Paarungen der naechsten Tage, auf die Schreibweise von football-data gebracht."""
    from datetime import date, timedelta
    heute = date.today()
    zeilen, ohne = [], []
    for liga, slug in ESPN_LIGEN.items():
        bekannt = teams_aus_datei(liga)
        if not bekannt:
            continue
        vergleich = [(n, normal(n)) for n in bekannt]
        gefunden = 0
        for versatz in range(VORLAUF_TAGE):
            tag = (heute + timedelta(days=versatz)).strftime("%Y%m%d")
            for iso, heim, gast in espn_holen(slug, tag):
                treffer = []
                for roh in (heim, gast):
                    kandidat, beste = None, 0.0
                    rn = normal(roh)
                    for name, nn in vergleich:
                        w = aehnlichkeit(rn, nn)
                        if w > beste:
                            beste, kandidat = w, name
                    treffer.append(kandidat if beste >= 0.6 else None)
                if all(treffer):
                    zeilen.append([liga, iso, treffer[0], treffer[1]])
                    gefunden += 1
                else:
                    ohne.append(f"{liga}: {heim} gegen {gast}")
            time.sleep(0.1)
        print(f"  {liga}: {gefunden} Partien zugeordnet")
    if ohne:
        print(f"  {len(ohne)} Partien ohne Zuordnung, davon:")
        for x in ohne[:10]:
            print("    " + x)
    return zeilen


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

    print("Fruehe Ansetzungen bei ESPN holen ...")
    fruehe = fruehe_ansetzungen()
    with open(f"{ORDNER}/fixtures-frueh.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Div", "Zeit", "HomeTeam", "AwayTeam"])
        w.writerows(fruehe)
    print(f"{ORDNER}/fixtures-frueh.csv: {len(fruehe)} Zeilen")

    print(f"\nFertig: {ok} Dateien geholt, {fehlt} nicht vorhanden.")


if __name__ == "__main__":
    main()
