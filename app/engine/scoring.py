"""
Scoring RELATIF. Les anciens scores partaient de 50 puis ajoutaient/retiraient des points selon des seuils
absolus (PER < 18, ROIC...) : ils saturaient à 0/100, ne tenaient pas compte du secteur ni du marché
(un PER de 18 n'a pas le même sens à Tokyo, dans la tech ou dans les banques) et mélangeaient les unités.

Ici chaque métrique est transformée en percentile (0-100) :
  • dans le secteur (si au moins 8 titres du secteur ont la donnée) pondéré 60 %
  • dans tout l'univers analysé, pondéré 40 %
puis moyennée par facteur. Les données manquantes sont ignorées (pas remplacées par un 50 neutre) et la
couverture est exposée. Le score final est le rang percentile du score composite : c'est un classement
relatif à l'indice choisi, pas une valeur absolue.
"""
import numpy as np
import pandas as pd

POIDS = {"valo": 0.30, "qual": 0.25, "crois": 0.15, "risq": 0.15, "mom": 0.15}

# (colonne, sens) — sens +1 : plus haut = mieux ; −1 : plus bas = mieux
METRIQUES = {
    "std": {
        "valo": [("fcf_yield", 1), ("earn_yield", 1), ("ebitda_yield", 1), ("marge_secu", 1)],
        "qual": [("roic", 1), ("spread", 1), ("pio_ratio", 1), ("marge_op", 1)],
        "crois": [("cagr_ca", 1), ("cagr_fcf", 1)],
        "risq": [("nd_ebitda", -1), ("vol", -1), ("mdd_abs", -1), ("beta", -1), ("altman_niv", 1)],
        "mom": [("mom_12_1", 1), ("dist_ma200", 1)],
    },
    "fin": {   # banques / assurances : FCF, EBITDA et dette nette n'ont pas de sens
        "valo": [("earn_yield", 1), ("marge_secu", 1), ("div_yield", 1)],
        "qual": [("roe", 1), ("roa", 1)],
        "crois": [("cagr_ca", 1)],
        "risq": [("vol", -1), ("mdd_abs", -1), ("beta", -1)],
        "mom": [("mom_12_1", 1), ("dist_ma200", 1)],
    },
}
TOUTES = sorted({c for t in METRIQUES.values() for f in t.values() for c, _ in f})
SEUIL_SECTEUR = 8
SEUIL_MIN_DONNEES = 5
REGLAGES_DEFAUT = {"achat_fort": 90, "achat": 75, "vente": 20, "couverture_min": 50, "poids_secteur": 60}


def _borne(x, lo, hi, defaut):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return defaut
    return defaut if x != x else min(hi, max(lo, x))


def normaliser_reglages(brut=None):
    """Réglages saisis dans l'interface (pondérations et seuils en %/points) -> valeurs bornées et cohérentes :
    pondérations ramenées à une somme de 1, achat fort >= achat > vente. À n'appliquer qu'UNE fois sur les
    réglages bruts ; calculer_scores attend le résultat."""
    brut = brut if isinstance(brut, dict) else {}
    pb = brut.get("poids") if isinstance(brut.get("poids"), dict) else {}
    poids = {k: _borne(pb.get(k), 0, 100, POIDS[k] * 100) for k in POIDS}
    total = sum(poids.values())
    poids = {k: (v / total if total > 0 else POIDS[k]) for k, v in poids.items()}
    achat = int(_borne(brut.get("achat"), 50, 99, REGLAGES_DEFAUT["achat"]))
    return {"poids": poids, "achat": achat,
            "achat_fort": int(max(achat, _borne(brut.get("achat_fort"), 50, 100, REGLAGES_DEFAUT["achat_fort"]))),
            "vente": int(min(achat - 1, _borne(brut.get("vente"), 1, 60, REGLAGES_DEFAUT["vente"]))),
            "couverture_min": _borne(brut.get("couverture_min"), 0, 100, REGLAGES_DEFAUT["couverture_min"]),
            "poids_secteur": _borne(brut.get("poids_secteur"), 0, 100, REGLAGES_DEFAUT["poids_secteur"]) / 100}


def _percentile(df, col, sens, w_sec=0.6):
    """Percentile 0-100 (rang centré (r−0,5)/n), mix secteur/univers ; NaN si < 5 valeurs dans l'univers."""
    s = pd.to_numeric(df[col], errors="coerce")
    n_uni = s.count()
    if n_uni < SEUIL_MIN_DONNEES:
        return pd.Series(np.nan, index=df.index)
    p_uni = (s.rank(method="average") - 0.5) / n_uni
    grp = df["secteur"]
    n_sec = s.groupby(grp).transform("count")
    p_sec = (s.groupby(grp).rank(method="average") - 0.5) / n_sec.replace(0, np.nan)
    p = pd.Series(np.where(n_sec >= SEUIL_SECTEUR, w_sec * p_sec + (1 - w_sec) * p_uni, p_uni), index=df.index)
    p = p.where(s.notna())
    return (p if sens > 0 else 1 - p) * 100


def calculer_scores(lignes, reglages=None):
    """lignes : liste de dicts (sorties de fetcher). reglages : sortie de normaliser_reglages (défauts si None).
    Retourne {ticker: {score, valo, qual, crois, risq, mom,
    signal, couverture, alertes_score}}."""
    if not lignes:
        return {}
    reg = reglages or normaliser_reglages(None)
    poids = reg["poids"]
    df = pd.DataFrame(lignes).reset_index(drop=True)
    for col in ["secteur", "est_fin", "piotroski", "piotroski_n", "mdd", "altman_zone", "marge_secu"]:
        if col not in df:
            df[col] = None
    df["secteur"] = df["secteur"].fillna("N/A")
    df["est_fin"] = df["est_fin"].fillna(False).astype(bool)
    pn = pd.to_numeric(df["piotroski_n"], errors="coerce")
    df["pio_ratio"] = np.where(pn >= 6, pd.to_numeric(df["piotroski"], errors="coerce") / pn, np.nan)
    df["mdd_abs"] = -pd.to_numeric(df["mdd"], errors="coerce")
    df["altman_niv"] = df["altman_zone"].map({"sûre": 2.0, "grise": 1.0, "détresse": 0.0})
    for col in TOUTES:
        if col not in df:
            df[col] = np.nan

    # percentiles de toutes les métriques utilisées
    sens_col = {c: s for t in METRIQUES.values() for f in t.values() for c, s in f}
    pct = {c: _percentile(df, c, sens_col[c], reg["poids_secteur"]) for c in TOUTES}

    facteurs, couverture = {}, pd.Series(0.0, index=df.index)
    for f in poids:
        vals = {}
        for type_ in ("std", "fin"):
            cols = [c for c, _ in METRIQUES[type_][f]]
            vals[type_] = pd.concat([pct[c] for c in cols], axis=1).mean(axis=1, skipna=True)
        facteurs[f] = pd.Series(np.where(df["est_fin"], vals["fin"], vals["std"]), index=df.index)

    for type_, masque in (("std", ~df["est_fin"]), ("fin", df["est_fin"])):
        cols = [c for f in METRIQUES[type_].values() for c, _ in f]
        dispo = pd.concat([pct[c].notna() for c in cols], axis=1).sum(axis=1)
        couverture = couverture.where(~masque, dispo / len(cols) * 100)

    # score composite : un facteur sans aucune donnée est exclu (poids renormalisé), pas mis à 50
    num = sum(facteurs[f].fillna(0) * w for f, w in poids.items())
    den = sum(facteurs[f].notna() * w for f, w in poids.items())
    composite = num / den.replace(0, np.nan)
    n = composite.count()
    if n >= 12:
        score = (composite.rank(method="average") - 0.5) / n * 100
    else:                                   # univers trop petit pour un classement par rang
        score = composite

    res = {}
    for i, r in df.iterrows():
        f = {k: (None if pd.isna(facteurs[k][i]) else int(round(facteurs[k][i]))) for k in poids}
        v, q, ri = (50 if f[k] is None else f[k] for k in ("valo", "qual", "risq"))
        s = None if pd.isna(score[i]) else int(round(score[i]))
        cov = int(round(couverture[i]))
        alertes = []
        detresse = r.get("altman_zone") == "détresse"
        marge = r.get("marge_secu")
        marge = None if marge is None or pd.isna(marge) else float(marge)

        if detresse:
            alertes.append("Zone de détresse (Altman) : risque de défaut élevé")
        if v >= 70 and q <= 30:
            alertes.append("Bon marché mais faible qualité : piège de valeur possible")
        if s is not None and f["valo"] is not None and v <= 25 and s >= 60:
            alertes.append("Bonne société mais valorisation tendue")
        if s is None:
            alertes.append("Classement impossible : moins de 5 titres comparables dans cet univers")
        elif cov < reg["couverture_min"]:
            alertes.append(f"Données incomplètes ({cov} % des métriques disponibles)")

        if s is None or cov < reg["couverture_min"]:
            signal = "INSUFFISANT"
        elif s >= reg["achat_fort"] and v >= 50 and ri >= 40 and not detresse and (marge is None or marge > 0):
            signal = "ACHAT FORT"
        elif s >= reg["achat"] and ri >= 35 and not detresse and (marge is None or marge > -20):
            signal = "ACHAT"
        elif s <= reg["vente"] or ri <= 15 or detresse:
            signal = "VENTE"
        elif v <= 25 and s >= 60:
            signal = "CONSERVER (Trop chère)"
        else:
            signal = "CONSERVER"
        res[r["ticker"]] = {"score": s, "valo": f["valo"], "qual": f["qual"], "crois": f["crois"],
                            "risq": f["risq"], "mom": f["mom"], "signal": signal,
                            "couverture": cov, "alertes_score": alertes}
    return res
