#!/usr/bin/env python3
"""NFL: Sieg, Spread, Over/Under gesamt und je Team, Anytime Touchdown.

Das ganze Modell wird hier in der Automatik gerechnet; die App zeigt nur an.
Quelle fuer alles: die nflverse-Releases auf GitHub.

Kernideen, jeweils per Rueckvergleich an echten Spielen geprueft:

1. Touchdowns kommen fast nur aus Chancen nahe der Endzone. Jede Chance wird
   nach Feldzone (bis 5, bis 20, weiter weg) und Art (Lauf, Target) mit ihrer
   gemessenen Trefferquote gewichtet. Der Anteil eines Spielers an den
   gewichteten Chancen seines Teams verteilt die erwarteten Team-Touchdowns.
2. Die erwarteten Team-Punkte kommen aus der Marktlinie, sofern vorhanden.
   Im Rueckvergleich traf der Markt Endstaende deutlich besser als jedes
   reine Ergebnismodell - er ist deshalb der Anker, das Modell nur Ersatz.
3. Punktedifferenzen haeufen sich auf Schluesselzahlen (3, 7, 10). Fuer Sieg
   und Spread wird die Verteilung deshalb mit gemessenen Schluesselzahl-
   Gewichten gerechnet. Bei Summen und Team-Punkten brachte das im
   Rueckvergleich nichts, dort bleibt sie glatt.
4. Aktuelle Verletzungsmeldungen: Ausfaelle werden herausgenommen, ihre
   Chancen auf die Aktiven verteilt.

Erzeugt:
  daten/nfl-spiele.csv      kommende Partien mit Marktlinien und Modellwerten
  daten/nfl-linien.csv      faire Wahrscheinlichkeiten fuer Sieg, Spread, Totals
  daten/nfl-td.csv          Anytime-Touchdown je Spieler
  daten/nfl-rueckblick.csv  letzte abgeschlossene Woche: Prognose gegen Ergebnis
  daten/nfl-guete.csv       Kennzahlen aus dem Rueckvergleich
"""

import csv, io, os, time, urllib.error, urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BASIS = "https://github.com/nflverse/nflverse-data/releases/download"
ORDNER = "daten"
CACHE = os.environ.get("NFL_CACHE")          # nur zum lokalen Testen

HEUTE = date.today()
S = HEUTE.year if HEUTE.month >= 8 else HEUTE.year - 1

ZONEN = ["cnG", "cnR", "cnO", "tnG", "tnR", "tnO"]      # Laeufe/Targets je Zone
ZTD = ["ctdG", "ctdR", "ctdO", "ttdG", "ttdR", "ttdO"]  # Touchdowns je Zone

# Einstellungen aus dem Rueckvergleich
HW_SPIELER = 8        # Halbwertszeit der Spielerwerte, in Wochen
SCHRUMPF = 0.5        # Daempfung, in Spielen
VORSAISON = 0.6       # Gewicht der Vorsaison
BODEN_AKTIV = 0.85    # Untergrenze fuer die Summe der Aktiven, relativ zum Team
HW_TEAM = 12          # Halbwertszeit im Punktemodell, in Wochen
K_TEAM = 3            # Daempfung im Punktemodell, in Durchschnittsspielen


# ---------------------------------------------------------------- Abruf
def laden(pfad):
    if CACHE:
        lokal = os.path.join(CACHE, os.path.basename(pfad))
        if os.path.exists(lokal):
            return open(lokal, "rb").read()
    for i in range(3):
        try:
            req = urllib.request.Request(f"{BASIS}/{pfad}",
                                         headers={"User-Agent": "linien-modell/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            print(f"  {pfad}: HTTP {e.code}")
            return None
        except Exception as e:
            if i == 2:
                print(f"  {pfad}: {type(e).__name__}")
                return None
            time.sleep(3)


def csv_laden(pfad):
    roh = laden(pfad)
    return pd.read_csv(io.BytesIO(roh), low_memory=False) if roh else None


def schreiben(name, kopf, zeilen):
    with open(f"{ORDNER}/{name}", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        w.writerows(zeilen)
    print(f"{ORDNER}/{name}: {len(zeilen)} Zeilen")


# ---------------------------------------------------------------- Hilfen
def ncdf(x):
    """Normalverteilung, Abramowitz-Stegun, Fehler < 1e-7."""
    x = np.asarray(x, dtype=float)
    t = 1 / (1 + 0.2316419 * np.abs(x))
    d = 0.3989422804014327 * np.exp(-x * x / 2)
    p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
               + t * (-1.821255978 + t * 1.330274429))))
    return np.where(x > 0, 1 - p, p)


def dezimal(ml):
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    if np.isnan(ml) or ml == 0:
        return None
    return 1 + ml / 100 if ml > 0 else 1 + 100 / abs(ml)


def ohne_marge(q1, q2):
    if not q1 or not q2:
        return None
    a, b = 1 / q1, 1 / q2
    return a / (a + b)


def utc(tag, zeit):
    try:
        dt = datetime.strptime(f"{tag} {zeit}", "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def r2(x, n=4):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# ------------------------------------------------ Schluesselzahl-Verteilungen
class Verteilung:
    """Ganzzahlige Verteilung: Normalverteilung mal gemessene Schluesselgewichte."""

    def __init__(self, werte, mus, lo, hi, symm, daempf):
        self.idx = np.arange(lo, hi + 1)
        self.sigma = float(np.std(np.asarray(werte) - np.asarray(mus)))
        self.k = np.ones(len(self.idx))
        werte, mus = np.asarray(werte), np.asarray(mus)
        beob = np.zeros(len(self.idx))
        for v in werte:
            if lo <= v <= hi:
                beob[int(v) - lo] += 1
        for _ in range(3):
            erw = np.zeros(len(self.idx))
            for mu in mus:
                erw += self.wahrsch(mu)
            b, e = beob.copy(), erw.copy()
            if symm:
                b = (b + b[::-1]) / 2
                e = (e + e[::-1]) / 2
            self.k = self.k * (b + daempf) / (e + daempf)

    def wahrsch(self, mu, sigma=None):
        s = sigma or self.sigma
        p = ncdf((self.idx + 0.5 - mu) / s) - ncdf((self.idx - 0.5 - mu) / s)
        p = p * self.k
        return p / p.sum()

    def ueber(self, mu, linie, sigma=None):
        """(Wahrscheinlichkeit ueber, Wahrscheinlichkeit genau auf der Linie)."""
        p = self.wahrsch(mu, sigma)
        return float(p[self.idx > linie].sum()), float(p[self.idx == linie].sum())

    def mittel(self, mu, sigma=None):
        p = self.wahrsch(mu, sigma)
        return float((p * self.idx).sum())

    def mu_fuer_mittel(self, ziel, sigma=None):
        """Lageparameter, bei dem der Mittelwert der Verteilung 'ziel' ist.
        Durch die Schluesselzahlen weichen beide voneinander ab."""
        a, b = ziel - 15, ziel + 15
        for _ in range(40):
            m = (a + b) / 2
            if self.mittel(m, sigma) < ziel:
                a = m
            else:
                b = m
        return (a + b) / 2

    def mu_fuer(self, linie, p_ueber, sigma=None):
        """Mittelwert, bei dem 'ueber der Linie' (ohne Push) p_ueber ergibt."""
        a, b = linie - 12, linie + 12
        for _ in range(40):
            m = (a + b) / 2
            ue, pu = self.ueber(m, linie, sigma)
            if ue / max(1e-9, 1 - pu) < p_ueber:
                a = m
            else:
                b = m
        return (a + b) / 2


# ---------------------------------------------------------------- Punktemodell
def punktemodell(E, jetzt):
    """Angriff, Abwehr, Heimvorteil; E enthaelt nur Spiele vor 'jetzt'."""
    s = jetzt // 20 + 2000
    w = 0.5 ** ((jetzt - E.t) / HW_TEAM) * np.where(E.season < s, 0.55, 1.0)
    lg = (w * (E.home_score + E.away_score)).sum() / (2 * w.sum())
    teams = pd.unique(pd.concat([E.home_team, E.away_team]))
    att = {t: 1.0 for t in teams}
    de = {t: 1.0 for t in teams}
    hv = 1.03
    neutr = E.neutral.values == 1
    for _ in range(25):
        hf = np.where(neutr, 1.0, hv)
        af = np.where(neutr, 1.0, 1 / hv)
        ha, aa = E.home_team.map(att).values, E.away_team.map(att).values
        hd, ad = E.home_team.map(de).values, E.away_team.map(de).values
        schl = np.r_[E.home_team, E.away_team]
        num = pd.Series(np.r_[w * E.home_score, w * E.away_score]).groupby(schl).sum()
        den = pd.Series(np.r_[w * lg * hf * ad, w * lg * af * hd]).groupby(schl).sum()
        att = ((num + K_TEAM * lg) / (den + K_TEAM * lg)).to_dict()
        ha, aa = E.home_team.map(att).values, E.away_team.map(att).values
        num = pd.Series(np.r_[w * E.away_score, w * E.home_score]).groupby(schl).sum()
        den = pd.Series(np.r_[w * lg * af * aa, w * lg * hf * ha]).groupby(schl).sum()
        de = ((num + K_TEAM * lg) / (den + K_TEAM * lg)).to_dict()
        m = np.mean(list(att.values()))
        att = {k: v / m for k, v in att.items()}
        m = np.mean(list(de.values()))
        de = {k: v / m for k, v in de.items()}
        ha, aa = E.home_team.map(att).values, E.away_team.map(att).values
        hd, ad = E.home_team.map(de).values, E.away_team.map(de).values
        n = ~neutr
        zh = (w * E.home_score)[n].sum() / (w * lg * ha * ad)[n].sum()
        za = (w * E.away_score)[n].sum() / (w * lg * aa * hd)[n].sum()
        hv = float(np.sqrt(zh / za))

    def erw(heim, gast, neutral):
        f = 1.0 if neutral else hv
        return (lg * f * att.get(heim, 1) * de.get(gast, 1),
                lg / f * att.get(gast, 1) * de.get(heim, 1))
    return erw


# ---------------------------------------------------------------- Chancen je Spieler
def chancen_laden():
    teile = []
    spalten = ["game_id", "season", "week", "season_type", "posteam", "defteam",
               "play_type", "yardline_100", "rusher_player_id", "rusher_player_name",
               "receiver_player_id", "receiver_player_name", "rush_touchdown",
               "pass_touchdown", "two_point_attempt"]
    for j in (S - 2, S - 1, S):
        roh = laden(f"pbp/play_by_play_{j}.parquet")
        if not roh:
            continue
        d = pd.read_parquet(io.BytesIO(roh), columns=spalten)
        print(f"  Play-by-Play {j}: {len(d)} Spielzuege")
        teile.append(d)
    if not teile:
        return None
    p = pd.concat(teile)
    p = p[(p.season_type == "REG") & p.play_type.isin(["pass", "run"])
          & (p.two_point_attempt != 1) & p.posteam.notna()]
    p["z"] = np.where(p.yardline_100 <= 5, "G", np.where(p.yardline_100 <= 20, "R", "O"))

    def fassen(df, idc, namec, tdc, vor):
        g = (df.dropna(subset=[idc])
               .groupby(["game_id", "season", "week", "posteam", "defteam", idc, namec, "z"])
               .agg(n=("play_type", "size"), td=(tdc, "sum")).reset_index())
        w = g.pivot_table(index=["game_id", "season", "week", "posteam", "defteam", idc, namec],
                          columns="z", values=["n", "td"], fill_value=0)
        w.columns = [f"{vor}{a}{b}" for a, b in w.columns]
        return w.reset_index().rename(columns={idc: "id", namec: "kurz"})

    lauf = fassen(p[p.play_type == "run"], "rusher_player_id", "rusher_player_name",
                  "rush_touchdown", "c")
    ziel = fassen(p[p.play_type == "pass"], "receiver_player_id", "receiver_player_name",
                  "pass_touchdown", "t")
    k = ["game_id", "season", "week", "posteam", "defteam", "id"]
    D = pd.merge(lauf, ziel, on=k, how="outer", suffixes=("", "_z"))
    if "kurz_z" in D:
        D["kurz"] = D["kurz"].fillna(D["kurz_z"])
        D = D.drop(columns=["kurz_z"])
    for c in ZONEN + ZTD:
        if c not in D:
            D[c] = 0
    D[ZONEN + ZTD] = D[ZONEN + ZTD].fillna(0).astype(int)
    D["td"] = D[ZTD].sum(axis=1)
    D["t"] = (D.season - 2000) * 20 + D.week
    return D


def spielerwerte(hist, jetzt):
    """Gewichtete Chancen je Spiel: je Spieler (gedaempft) und je Team."""
    s = jetzt // 20 + 2000
    quote = hist[ZTD].sum().values / np.maximum(hist[ZONEN].sum().values, 1)
    roh = (hist[ZONEN].values * quote).sum(axis=1)
    w = 0.5 ** ((jetzt - hist.t.values) / HW_SPIELER) * np.where(hist.season.values < s, VORSAISON, 1.0)
    ids = hist.id.values
    pro = pd.Series(w * roh).groupby(ids).sum() / (pd.Series(w).groupby(ids).sum() + SCHRUMPF)
    tg = (pd.DataFrame({"g": hist.game_id.values, "tm": hist.posteam.values, "r": roh, "w": w})
            .groupby(["g", "tm"]).agg(r=("r", "sum"), w=("w", "first")).reset_index())
    team = (tg.w * tg.r).groupby(tg.tm).sum() / tg.w.groupby(tg.tm).sum()
    # Anschauliche Zahlen: Chancen bis 20 Yards und bis 5 Yards je Spiel
    rz = pd.Series(w * (hist.cnR + hist.cnG + hist.tnR + hist.tnG).values).groupby(ids).sum() \
        / (pd.Series(w).groupby(ids).sum() + SCHRUMPF)
    gl = pd.Series(w * (hist.cnG + hist.tnG).values).groupby(ids).sum() \
        / (pd.Series(w).groupby(ids).sum() + SCHRUMPF)
    return pro, team, quote, rz, gl


# ---------------------------------------------------------------- Hauptteil
def main():
    os.makedirs(ORDNER, exist_ok=True)
    print(f"Saison {S}")

    print("Spielplan holen ...")
    G = csv_laden("schedules/games.csv")
    if G is None:
        print("Ohne Spielplan kein Modell.")
        return
    G = G[G.game_type == "REG"].copy()
    G["t"] = (G.season - 2000) * 20 + G.week
    G["neutral"] = (G.location == "Neutral").astype(int)
    fertig = G[G.home_score.notna()].copy()

    # --- Schluesselzahl-Verteilungen, geschaetzt gegen die Schlusslinien
    L = fertig[(fertig.season >= S - 10) & fertig.spread_line.notna() & fertig.total_line.notna()]
    marge = (L.home_score - L.away_score).values
    summe = (L.home_score + L.away_score).values
    impH = ((L.total_line + L.spread_line) / 2).values
    impA = ((L.total_line - L.spread_line) / 2).values
    # Schluesselzahlen nur fuer die Differenz: dort verbesserten sie den Rueckvergleich,
    # bei Summe und Team-Punkten war die glatte Verteilung besser.
    VM = Verteilung(marge, L.spread_line.values, -70, 70, True, 30)
    VT = Verteilung(summe, L.total_line.values, 0, 120, False, 1e12)
    VP = Verteilung(np.r_[L.home_score, L.away_score], np.r_[impH, impA], 0, 75, False, 1e12)
    print(f"  Streuung um die Marktlinie: Differenz {VM.sigma:.1f}, "
          f"Summe {VT.sigma:.1f}, Team {VP.sigma:.1f} Punkte ({len(L)} Spiele)")

    # --- Punktemodell rueckwaerts pruefen: Streuung und Abweichung zum Markt
    E = fertig[fertig.season >= S - 5]
    bt = []
    for jetzt in sorted(E[E.season >= S - 2].t.unique()):
        erw = punktemodell(E[E.t < jetzt], jetzt)
        for _, g in E[E.t == jetzt].iterrows():
            mh, ma = erw(g.home_team, g.away_team, g.neutral)
            bt.append((mh, ma, g.home_score, g.away_score, g.spread_line, g.total_line))
    bt = pd.DataFrame(bt, columns=["mh", "ma", "hs", "as_", "sp", "tl"])
    sig_m = float(np.std((bt.hs - bt.as_) - (bt.mh - bt.ma)))
    sig_t = float(np.std((bt.hs + bt.as_) - (bt.mh + bt.ma)))
    sig_p = float(np.std(np.r_[bt.hs - bt.mh, bt.as_ - bt.ma]))
    guete = [("modell_sigma_differenz", r2(sig_m, 2)), ("modell_sigma_summe", r2(sig_t, 2)),
             ("markt_sigma_differenz", r2(VM.sigma, 2)), ("markt_sigma_summe", r2(VT.sigma, 2))]
    b2 = bt.dropna()
    for schw in (0, 3, 5):
        d = (b2.mh - b2.ma) - b2.sp
        m = np.abs(d) >= schw
        tr = (np.sign(d[m]) * np.sign(((b2.hs - b2.as_) - b2.sp)[m]))
        tr = tr[tr != 0]
        guete.append((f"abw_spread_{schw}", f"{r2(100 * (tr > 0).mean(), 1)}|{len(tr)}"))
        d = (b2.mh + b2.ma) - b2.tl
        m = np.abs(d) >= schw
        tr = (np.sign(d[m]) * np.sign(((b2.hs + b2.as_) - b2.tl)[m]))
        tr = tr[tr != 0]
        guete.append((f"abw_total_{schw}", f"{r2(100 * (tr > 0).mean(), 1)}|{len(tr)}"))
    print(f"  Punktemodell: Streuung Differenz {sig_m:.1f}, Summe {sig_t:.1f} "
          f"({len(bt)} Spiele im Rueckvergleich)")

    # --- Kommende Woche
    offen = G[(G.season == S) & G.home_score.isna()]
    if offen.empty:
        print("Keine offenen Spiele in dieser Saison.")
        U = offen
    else:
        U = offen[offen.week == offen.week.min()]
    jetzt = int(U.t.min()) if not U.empty else int(fertig.t.max()) + 1
    erw = punktemodell(E, jetzt)

    spiele, linien, markt_pkt = [], [], {}
    for _, g in U.iterrows():
        mh, ma = erw(g.home_team, g.away_team, g.neutral)
        qsh, qsa = dezimal(g.home_spread_odds), dezimal(g.away_spread_odds)
        qo, qu = dezimal(g.over_odds), dezimal(g.under_odds)
        qmh, qma = dezimal(g.home_moneyline), dezimal(g.away_moneyline)
        hat_markt = not (pd.isna(g.spread_line) or pd.isna(g.total_line))
        basen = []
        if hat_markt:
            # Lage so waehlen, dass die Quoten ohne Marge exakt getroffen werden
            ph = ohne_marge(qsh, qsa)
            mu_m = VM.mu_fuer(g.spread_line, ph) if ph else VM.mu_fuer_mittel(g.spread_line)
            po = ohne_marge(qo, qu)
            mu_t = VT.mu_fuer(g.total_line, po) if po else VT.mu_fuer_mittel(g.total_line)
            e_m, e_t = VM.mittel(mu_m), VT.mittel(mu_t)
            ph_pkt, pa_pkt = (e_t + e_m) / 2, (e_t - e_m) / 2
            markt_pkt[g.game_id] = (ph_pkt, pa_pkt)
            basen.append(("markt", mu_m, mu_t, VP.mu_fuer_mittel(ph_pkt), VP.mu_fuer_mittel(pa_pkt),
                          VM.sigma, VT.sigma, VP.sigma))
            z_sp, z_to, z_h, z_a = float(g.spread_line), float(g.total_line), ph_pkt, pa_pkt
        else:
            z_sp, z_to, z_h, z_a = round((mh - ma) * 2) / 2, mh + ma, mh, ma
        basen.append(("modell", VM.mu_fuer_mittel(mh - ma, sig_m), VT.mu_fuer_mittel(mh + ma, sig_t),
                      VP.mu_fuer_mittel(mh, sig_p), VP.mu_fuer_mittel(ma, sig_p),
                      sig_m, sig_t, sig_p))
        spiele.append([g.game_id, S, int(g.week), utc(g.gameday, g.gametime),
                       g.home_team, g.away_team, int(g.neutral),
                       r2(g.spread_line, 1), r2(g.total_line, 1),
                       r2(qsh, 3), r2(qsa, 3), r2(qo, 3), r2(qu, 3), r2(qmh, 3), r2(qma, 3),
                       r2(markt_pkt.get(g.game_id, (None,))[0], 2),
                       r2(markt_pkt.get(g.game_id, (None, None))[1], 2),
                       r2(mh, 2), r2(ma, 2), g.get("roof", ""), r2(g.get("wind"), 0)])
        for basis, mu_m, mu_t, mu_h, mu_a, sm, st, sp in basen:
            p = VM.wahrsch(mu_m, sm)
            p0 = float(p[VM.idx == 0].sum())
            linien.append([g.game_id, basis, "sieg", "",
                           r2(float(p[VM.idx > 0].sum()) / max(1e-9, 1 - p0)), 0])
            # Spread: Heim gewinnt mit mehr als 'vor' Punkten; zentriert auf die Marktlinie
            for d in np.arange(-3.5, 4, 0.5):
                vor = z_sp + d
                ue, pu = VM.ueber(mu_m, vor, sm)
                linien.append([g.game_id, basis, "spread", r2(-vor, 1), r2(ue), r2(pu)])
            mitte = round(z_to)
            for d in range(-5, 6):
                ue, pu = VT.ueber(mu_t, mitte + d - 0.5, st)
                linien.append([g.game_id, basis, "total", mitte + d - 0.5, r2(ue), r2(pu)])
            for seite, mu, z in (("heim", mu_h, z_h), ("gast", mu_a, z_a)):
                mitte = round(z)
                for d in range(-3, 4):
                    ue, pu = VP.ueber(mu, mitte + d - 0.5, sp)
                    linien.append([g.game_id, basis, seite, mitte + d - 0.5, r2(ue), r2(pu)])

    schreiben("nfl-spiele.csv",
              ["Spiel", "Saison", "Woche", "Zeit", "Heim", "Gast", "Neutral",
               "Spread", "Total", "QSpreadHeim", "QSpreadGast", "QOver", "QUnder",
               "QSiegHeim", "QSiegGast", "MarktPktHeim", "MarktPktGast",
               "ModellPktHeim", "ModellPktGast", "Dach", "Wind"], spiele)
    schreiben("nfl-linien.csv", ["Spiel", "Basis", "Markt", "Linie", "P", "Push"], linien)

    # --- Touchdowns
    print("Play-by-Play holen ...")
    D = chancen_laden()
    if D is None:
        print("Keine Play-by-Play-Daten, Touchdowns entfallen.")
        schreiben("nfl-guete.csv", ["Schluessel", "Wert"], guete)
        return

    kader = csv_laden(f"weekly_rosters/roster_weekly_{S}.csv")
    if kader is None or kader.empty:
        kader = csv_laden(f"rosters/roster_{S}.csv")
    namen, pos, team_akt, status = {}, {}, {}, {}
    if kader is not None and not kader.empty:
        if "week" in kader:
            kader = kader.sort_values("week").groupby("gsis_id").tail(1)
        for _, r in kader.iterrows():
            namen[r.gsis_id] = r.full_name
            pos[r.gsis_id] = r.position
            team_akt[r.gsis_id] = r.team
            status[r.gsis_id] = str(r.get("status", "ACT"))
    verletzt = {}
    inj = csv_laden(f"injuries/injuries_{S}.csv")
    if inj is not None and not inj.empty and not U.empty:
        inj = inj[inj.week == U.week.min()]
        for _, r in inj.iterrows():
            if isinstance(r.report_status, str):
                verletzt[r.gsis_id] = r.report_status
    print(f"  Kader: {len(namen)} Spieler, Verletzungsmeldungen: {len(verletzt)}")

    # Rueckvergleich fuer die Kalibrierung: jede Woche aus Daten davor vorhergesagt
    Lk = G.set_index("game_id")[["home_team", "spread_line", "total_line"]]
    zeilen = []
    for t in sorted(D[D.season >= S - 1].t.unique()):
        hist, cur = D[D.t < t], D[D.t == t]
        if hist.empty:
            continue
        pro, team, _, _, _ = spielerwerte(hist, t)
        c = cur[["game_id", "posteam", "id", "td"]].copy()
        c["pr"] = c.id.map(pro).fillna(0).values
        c["tr"] = c.posteam.map(team).values
        c["akt"] = c.groupby(["game_id", "posteam"]).pr.transform("sum")
        c["t"] = t
        zeilen.append(c)
    K = pd.concat(zeilen).dropna(subset=["tr"]).join(Lk, on="game_id").dropna(subset=["spread_line"])
    K["imp"] = np.where(K.posteam == K.home_team, (K.total_line + K.spread_line) / 2,
                        (K.total_line - K.spread_line) / 2)
    K["anteil"] = K.pr / np.maximum(K.akt, BODEN_AKTIV * K.tr)
    y = (K.td > 0).astype(float).values

    def verlust(p):
        p = np.clip(p, 0.005, 0.995)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    best = None
    for c in np.arange(0.04, 0.12, 0.0025):
        for b in np.arange(0.5, 1.05, 0.05):
            v = verlust(1 - np.exp(-np.maximum(K.imp * c * K.anteil, 1e-4) ** b))
            if best is None or v < best[0]:
                best = (v, c, b)
    ll, C_TD, B_TD = best
    K["p"] = 1 - np.exp(-np.maximum(K.imp * C_TD * K.anteil, 1e-4) ** B_TD)
    print(f"  Touchdown-Kalibrierung: c={C_TD:.4f} b={B_TD:.2f}, "
          f"Treffgenauigkeit {ll:.4f} gegen {verlust(np.full_like(y, y.mean())):.4f} "
          f"fuer den blossen Durchschnitt ({len(K)} Prognosen)")
    guete += [("td_c", r2(C_TD)), ("td_b", r2(B_TD, 2)), ("td_n", len(K)),
              ("td_verlust", r2(ll)), ("td_verlust_schnitt", r2(verlust(np.full_like(y, y.mean())))),
              ("td_quote", r2(y.mean()))]
    fach = pd.cut(K.p, [0, .1, .2, .3, .4, .5, .6, 1])
    for iv, grp in K.groupby(fach, observed=True):
        guete.append((f"td_fach_{iv.left:.1f}-{iv.right:.1f}",
                      f"{r2(grp.p.mean(), 3)}|{r2((grp.td > 0).mean(), 3)}|{len(grp)}"))

    # Prognose fuer die kommende Woche
    pro, team, quote, rz, gl = spielerwerte(D, jetzt)
    kurz = D.sort_values("t").groupby("id").kurz.last()
    td_zeilen = []
    for _, g in U.iterrows():
        for tm, geg, heim in ((g.home_team, g.away_team, True), (g.away_team, g.home_team, False)):
            if g.game_id in markt_pkt:
                pkt = markt_pkt[g.game_id][0 if heim else 1]
                quelle = "markt"
            else:
                mh, ma = erw(g.home_team, g.away_team, g.neutral)
                pkt = mh if heim else ma
                quelle = "modell"
            kand = [i for i, t in team_akt.items() if t == tm and i in pro.index and pro[i] > 0
                    and status.get(i, "ACT") == "ACT"]
            fehlt = {i for i in kand if verletzt.get(i) in ("Out", "Doubtful")}
            summe_akt = sum(pro[i] for i in kand if i not in fehlt)
            nenner = max(summe_akt, BODEN_AKTIV * float(team.get(tm, summe_akt or 1)))
            for i in kand:
                anteil = pro[i] / nenner if nenner > 0 else 0
                lam = max(pkt * C_TD * anteil, 1e-4) ** B_TD
                p = 0.0 if verletzt.get(i) == "Out" else 1 - np.exp(-lam)
                if p < 0.03 and verletzt.get(i) != "Out":
                    continue
                if verletzt.get(i) == "Out" and anteil < 0.05:
                    continue
                td_zeilen.append([g.game_id, tm, geg, i, namen.get(i, kurz.get(i, i)),
                                  pos.get(i, ""), verletzt.get(i, ""),
                                  r2(rz.get(i, 0), 2), r2(gl.get(i, 0), 2),
                                  r2(anteil, 3), r2(lam), r2(p), quelle])
    td_zeilen.sort(key=lambda z: (z[0], z[1], -(z[11] or 0)))
    schreiben("nfl-td.csv", ["Spiel", "Team", "Gegner", "SpielerId", "Name", "Position",
                             "Status", "ChancenRZ", "ChancenGL", "Anteil", "Lambda", "P",
                             "Quelle"], td_zeilen)

    # Rueckblick auf die letzte abgeschlossene Woche
    rb = []
    # letzte vollstaendige Woche: die vor der kommenden (Donnerstagsspiel zaehlt nicht)
    t_letzt = int(D[D.t < jetzt].t.max()) if (D.t < jetzt).any() else int(D.t.max())
    Kr = K[K.t == t_letzt]
    kurzname = D.drop_duplicates("id").set_index("id").kurz
    for _, r in Kr.sort_values("p", ascending=False).iterrows():
        if r.p < 0.05 and r.td == 0:
            continue
        rb.append(["td", r.game_id, r.posteam, namen.get(r.id, kurzname.get(r.id, r.id)),
                   r2(r.p), int(r.td), ""])
    Gl = fertig[fertig.t == t_letzt]
    Eh = E[E.t < t_letzt]
    if not Eh.empty:
        erw_alt = punktemodell(Eh, t_letzt)
        for _, g in Gl.iterrows():
            mh, ma = erw_alt(g.home_team, g.away_team, g.neutral)
            rb.append(["spiel", g.game_id, f"{g.away_team}@{g.home_team}",
                       f"{int(g.away_score)}:{int(g.home_score)}",
                       r2(mh - ma, 1), r2(g.spread_line, 1),
                       f"{r2(mh + ma, 1)}|{r2(g.total_line, 1)}"])
    schreiben("nfl-rueckblick.csv",
              ["Typ", "Spiel", "Team", "Name", "P", "Ist", "Zusatz"], rb)
    guete.append(("rueckblick_woche", f"{t_letzt // 20 + 2000}|{t_letzt % 20}"))
    schreiben("nfl-guete.csv", ["Schluessel", "Wert"], guete)


if __name__ == "__main__":
    main()
