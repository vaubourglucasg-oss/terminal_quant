"""
Fonctions mathématiques du terminal. Aucune dépendance réseau (pandas / numpy uniquement),
donc testables seules. Convention : les ratios « financiers » sont des fractions (0.12 = 12 %),
les métriques renvoyées pour affichage (vol, drawdown, momentum...) sont déjà en pourcentage.
"""
import math
import numpy as np
import pandas as pd

JOURS_AN = 252
PRIME_RISQUE_MARCHE = 0.055          # prime de risque actions (ERP) — hypothèse globale
SECTEURS_MANUFACTURIERS = {"Industrials", "Basic Materials", "Consumer Cyclical",
                           "Consumer Defensive", "Energy"}


# --------------------------------------------------------------------------- #
# Lecture des états financiers (yfinance : colonnes = exercices, du plus récent au plus ancien)
# --------------------------------------------------------------------------- #
def ligne(df, *noms):
    """Première ligne trouvée parmi `noms`, sous forme de liste alignée sur les exercices
    (le plus récent en premier). Les valeurs manquantes restent None pour ne pas décaler les années."""
    if df is None or getattr(df, "empty", True):
        return []
    try:
        df = df.sort_index(axis=1, ascending=False)
    except Exception:
        pass
    for nom in noms:
        if nom in df.index:
            serie = pd.to_numeric(df.loc[nom], errors="coerce")
            valeurs = [None if pd.isna(x) else float(x) for x in serie.tolist()]
            if any(v is not None for v in valeurs):
                return valeurs
    return []


def val(liste, i):
    try:
        x = liste[i]
    except (IndexError, TypeError):
        return None
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return float(x)


def _ratio(a, b):
    return None if a is None or b is None or b <= 0 else a / b


# --------------------------------------------------------------------------- #
# Croissance
# --------------------------------------------------------------------------- #
def calculer_cagr(v0, v1, annees):
    """CAGR entre v0 (ancien) et v1 (récent). None si non défini (valeur <= 0).
    Renvoyer 0.0 comme avant faisait passer une donnée absente pour une croissance nulle."""
    if v0 is None or v1 is None or annees <= 0 or v0 <= 0 or v1 <= 0:
        return None
    return (v1 / v0) ** (1 / annees) - 1


def cagr_serie(liste, annees=3):
    """CAGR sur `annees` ans à partir d'une série alignée (récent en premier) ; repli sur 2 ans."""
    for n in (annees, 2):
        if n <= annees:
            c = calculer_cagr(val(liste, n), val(liste, 0), n)
            if c is not None:
                return c
    return None


# --------------------------------------------------------------------------- #
# Qualité / solidité
# --------------------------------------------------------------------------- #
def calculer_piotroski(fin, bs, cf):
    """F-score de Piotroski. Retourne (score, nb_criteres_evaluables) : un critère dont les
    données manquent n'est plus compté comme un échec silencieux."""
    ni = ligne(fin, "Net Income", "Net Income Common Stockholders")
    ca_rev = ligne(fin, "Total Revenue")
    gp = ligne(fin, "Gross Profit")
    sh = ligne(fin, "Basic Average Shares", "Diluted Average Shares") or ligne(bs, "Ordinary Shares Number")
    ta = ligne(bs, "Total Assets")
    ltd = ligne(bs, "Long Term Debt")
    ac = ligne(bs, "Current Assets")
    pc = ligne(bs, "Current Liabilities")
    cfo = ligne(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")

    score = n = 0

    def test(cond):
        nonlocal score, n
        if cond is None:
            return
        n += 1
        score += 1 if cond else 0

    roa0, roa1 = _ratio(val(ni, 0), val(ta, 0)), _ratio(val(ni, 1), val(ta, 1))
    test(None if roa0 is None else roa0 > 0)                                   # 1. ROA > 0
    test(None if val(cfo, 0) is None else val(cfo, 0) > 0)                     # 2. CFO > 0
    test(None if roa0 is None or roa1 is None else roa0 > roa1)                # 3. ROA en hausse
    test(None if val(cfo, 0) is None or val(ni, 0) is None else val(cfo, 0) > val(ni, 0))  # 4. qualité des gains
    if ta and val(ta, 0) and val(ta, 1):                                       # 5. levier en baisse
        l0 = (val(ltd, 0) or 0.0) / val(ta, 0)
        l1 = (val(ltd, 1) or 0.0) / val(ta, 1)
        test(l0 <= l1)
    else:
        test(None)
    cr0, cr1 = _ratio(val(ac, 0), val(pc, 0)), _ratio(val(ac, 1), val(pc, 1))
    test(None if cr0 is None or cr1 is None else cr0 > cr1)                    # 6. liquidité en hausse
    s0, s1 = val(sh, 0), val(sh, 1)
    test(None if s0 is None or s1 is None else s0 <= s1 * 1.005)               # 7. pas de dilution
    gm0, gm1 = _ratio(val(gp, 0), val(ca_rev, 0)), _ratio(val(gp, 1), val(ca_rev, 1))
    test(None if gm0 is None or gm1 is None else gm0 > gm1)                    # 8. marge brute en hausse
    at0, at1 = _ratio(val(ca_rev, 0), val(ta, 0)), _ratio(val(ca_rev, 1), val(ta, 1))
    test(None if at0 is None or at1 is None else at0 > at1)                    # 9. rotation des actifs
    return score, n


def calculer_altman(secteur, total_actifs, total_dettes, fonds_roulement, reserves, ebit,
                    capitalisation, fonds_propres, ca):
    """Altman Z (industriels cotés) ou Z'' (hors industrie), chacun avec ses seuils.
    Retourne (z, zone) ; zone ∈ {'sûre', 'grise', 'détresse'} ; (None, None) si données insuffisantes."""
    if not total_actifs or total_actifs <= 0 or not total_dettes or total_dettes <= 0:
        return None, None
    if None in (fonds_roulement, reserves, ebit):
        return None, None
    x1, x2, x3 = fonds_roulement / total_actifs, reserves / total_actifs, ebit / total_actifs
    if secteur in SECTEURS_MANUFACTURIERS and capitalisation and ca is not None:
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * (capitalisation / total_dettes) + 1.0 * (ca / total_actifs)
        haut, bas = 2.99, 1.81
    elif fonds_propres is not None:
        z = 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * (fonds_propres / total_dettes)
        haut, bas = 2.6, 1.1
    else:
        return None, None
    zone = "sûre" if z > haut else ("détresse" if z < bas else "grise")
    return round(z, 2), zone


def taux_effectif(fin, defaut=0.25):
    """Taux d'impôt effectif (médiane des 3 derniers exercices), borné [10 %, 35 %]."""
    impots = ligne(fin, "Tax Provision", "Income Tax Expense")
    avant = ligne(fin, "Pretax Income")
    taux = []
    for i in range(3):
        t, p = val(impots, i), val(avant, i)
        if t is not None and p is not None and p > 0 and 0 <= t / p <= 0.5:
            taux.append(t / p)
    return min(0.35, max(0.10, float(np.median(taux)))) if taux else defaut


def calculer_roic(ebit, taux_is, fonds_propres, dette, tresorerie):
    """ROIC en % = EBIT×(1−t) / capital investi. Le capital investi = fonds propres COMPTABLES + dette
    − trésorerie (plafonnée : au moins 20 % de FP + dette). L'ancien code utilisait la capitalisation
    boursière en repli, ce qui rendait le ROIC dépendant du cours."""
    if None in (ebit, fonds_propres, dette, tresorerie):
        return None
    base = fonds_propres + dette
    if base <= 0:
        return None
    capital = max(base - max(tresorerie, 0.0), 0.2 * base)
    return ebit * (1 - taux_is) / capital * 100


# --------------------------------------------------------------------------- #
# Coût du capital
# --------------------------------------------------------------------------- #
def calculer_cout_capitaux(rf, beta, prime_pays=0.0, erp=PRIME_RISQUE_MARCHE):
    b = min(max(beta if beta is not None else 1.0, 0.3), 2.5)
    return max(rf + 0.03, rf + b * erp + prime_pays)


def calculer_cout_dette(rf, charges_interets, dette, nd_ebitda):
    """Coût de la dette : charges d'intérêts / dette si cohérent, sinon rf + spread selon le levier.
    Toujours >= rf + 0,5 % (une dette ne coûte pas moins que l'État)."""
    if dette and dette > 0 and charges_interets and charges_interets > 0:
        return min(0.15, max(rf + 0.005, charges_interets / dette))
    spread = 0.07 if nd_ebitda is None else (0.015 if nd_ebitda < 1.5 else (0.035 if nd_ebitda < 3.0 else 0.07))
    return rf + spread


def calculer_wacc(ke, kd, taux_is, capitalisation, dette):
    v = (capitalisation or 0) + (dette or 0)
    if v <= 0:
        return ke
    return capitalisation / v * ke + dette / v * kd * (1 - taux_is)


# --------------------------------------------------------------------------- #
# Valorisation intrinsèque
# --------------------------------------------------------------------------- #
def projeter_dcf(fcf0, g1, ke, g_terminal, annees=10, palier=5):
    """DCF en 2 temps + fade : croissance g1 pendant `palier` ans, puis convergence linéaire vers
    g_terminal jusqu'à l'année `annees`, puis valeur terminale de Gordon.
    Retourne (valeur_actualisée_des_fonds_propres, part_de_la_valeur_terminale) ou None."""
    if fcf0 is None or fcf0 <= 0 or ke - g_terminal < 0.02:
        return None
    flux, f = 0.0, fcf0
    g = g1
    for t in range(1, annees + 1):
        g = g1 if t <= palier else g1 + (g_terminal - g1) * (t - palier) / (annees - palier)
        f *= 1 + g
        flux += f / (1 + ke) ** t
    vt = f * (1 + g_terminal) / (ke - g_terminal) / (1 + ke) ** annees
    total = flux + vt
    return (total, vt / total) if total > 0 else None


def croissance_retenue(cagr_ca, cagr_fcf, g_terminal):
    """Croissance de départ du DCF : moyenne des CAGR observés, bornée puis ramenée à 60/40 vers
    la croissance de long terme (la croissance passée se prolonge rarement telle quelle)."""
    obs = [x for x in (cagr_ca, cagr_fcf) if x is not None]
    if not obs:
        return g_terminal
    brut = min(0.20, max(-0.05, sum(obs) / len(obs)))
    return min(0.12, max(-0.03, 0.6 * brut + 0.4 * g_terminal))


def croissance_implicite(prix, fcf0, actions, ke, g_terminal):
    """DCF inversé : croissance g1 que le cours actuel suppose (dichotomie). None si hors [−25 %, 40 %]."""
    cible = prix * actions

    def ecart(g):
        r = projeter_dcf(fcf0, g, ke, g_terminal)
        return None if r is None else r[0] - cible

    lo, hi = -0.25, 0.40
    e_lo, e_hi = ecart(lo), ecart(hi)
    if e_lo is None or e_hi is None or e_lo > 0 or e_hi < 0:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        e = ecart(mid)
        if e is None:
            return None
        lo, hi = (mid, hi) if e < 0 else (lo, mid)
    return (lo + hi) / 2


SCENARIOS = (("bear", -1), ("base", 0), ("bull", 1))   # multiplicateur des écarts : g + m·Δg, ke − m·Δke


def valorisation_dcf(fcf0, actions, cagr_ca, cagr_fcf, ke, g_terminal, prix, dg=0.03, dk=0.01):
    """Valeur par action en 3 scénarios (g ± dg, ke ∓ dk ; par défaut ±3 pts et ∓1 pt) + DCF inversé + poids de la valeur terminale."""
    g1 = croissance_retenue(cagr_ca, cagr_fcf, g_terminal)
    out = {"bear": None, "base": None, "bull": None, "g1": g1, "part_vt": None, "g_implicite": None}
    if not actions or actions <= 0:
        return out
    for nom, mult in SCENARIOS:
        r = projeter_dcf(fcf0, g1 + mult * dg, ke - mult * dk, g_terminal)
        if r:
            out[nom] = r[0] / actions
            if nom == "base":
                out["part_vt"] = r[1]
    if prix and prix > 0 and out["base"]:
        out["g_implicite"] = croissance_implicite(prix, fcf0, actions, ke, g_terminal)
    return out


def valeur_pb_justifie(roe, bvps, ke, g):
    """Banques/assurances : P/B justifié = (ROE − g)/(ke − g), appliqué à l'actif net par action."""
    if roe is None or bvps is None or bvps <= 0 or ke - g < 0.02:
        return None
    return max((roe - g) / (ke - g), 0.0) * bvps


def valorisation_financiere(roe, bvps, ke, g, prix, dk=0.01):
    """Même logique 3 scénarios pour les financières, ROE ramené à 70/30 vers ke (ROE non durable)."""
    if roe is None:
        return {"bear": None, "base": None, "bull": None}
    roe_s = 0.7 * roe + 0.3 * ke
    return {nom: valeur_pb_justifie(roe_s + 2 * mult * dk, bvps, ke - mult * dk, g)
            for nom, mult in SCENARIOS}


def valeur_graham(eps, bvps):
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def marge_securite(valeur, prix):
    """(valeur − prix) / valeur, en %."""
    if not valeur or valeur <= 0 or not prix or prix <= 0:
        return None
    return (valeur - prix) / valeur * 100


# --------------------------------------------------------------------------- #
# Marché : technique, risque, bêta
# --------------------------------------------------------------------------- #
def calculer_rsi(close, n=14):
    """RSI de Wilder (lissage exponentiel alpha=1/n). Avant : moyenne simple, qui dévie du RSI standard."""
    d = close.diff()
    gain, perte = d.clip(lower=0), -d.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    al = perte.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rsi = 100 - 100 / (1 + ag / al.replace(0, np.nan))
    rsi = rsi.where(al != 0, 100.0)
    rsi = rsi.where(~((al == 0) & (ag == 0)), 50.0)
    return rsi.where(ag.notna())


def _hebdo(s):
    s = s.dropna().copy()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s.resample("W-FRI").last().dropna()


def calculer_beta(close, bench, min_obs=52):
    """Bêta sur rendements hebdomadaires (limite l'effet des fuseaux horaires) vs l'indice local,
    corrigé de Blume (0,67·β + 0,33). Le bêta Yahoo est calculé contre le S&P 500 : peu pertinent
    pour un titre japonais ou brésilien."""
    if bench is None or close is None or len(bench) < 60:
        return None
    ra, rb = _hebdo(close).pct_change(), _hebdo(bench).pct_change()
    df = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(df) < min_obs:
        return None
    var = df.iloc[:, 1].var()
    if not var or var <= 0:
        return None
    return float(0.67 * df.iloc[:, 0].cov(df.iloc[:, 1]) / var + 0.33)


def metriques_marche(close, rf=0.0, bench=None):
    """Indicateurs de risque et de tendance sur 1 an (rendements journaliers). Valeurs en % sauf
    Sharpe/Sortino/RSI/bêta. Sans assez d'historique, les champs restent None (jamais 0 par défaut :
    avant, un prix > MA=0 donnait +50 points de momentum à un titre récent)."""
    cles = ("prix", "ma50", "ma200", "rsi", "vol", "mdd", "rdt_1a", "sharpe", "sortino",
            "mom_12_1", "dist_ma200", "dist_ma50", "dist_52w", "beta")
    out = {k: None for k in cles}
    c = close.dropna() if close is not None else pd.Series(dtype=float)
    n = len(c)
    if n < 60:
        return out
    out["prix"] = float(c.iloc[-1])
    if n >= 50:
        out["ma50"] = float(c.rolling(50).mean().iloc[-1])
        out["dist_ma50"] = (out["prix"] / out["ma50"] - 1) * 100
    if n >= 200:
        out["ma200"] = float(c.rolling(200).mean().iloc[-1])
        out["dist_ma200"] = (out["prix"] / out["ma200"] - 1) * 100
    rsi = calculer_rsi(c).iloc[-1]
    out["rsi"] = None if pd.isna(rsi) else float(rsi)

    w = c.iloc[-(JOURS_AN + 1):]
    r = w.pct_change().dropna()
    vol = float(r.std() * math.sqrt(JOURS_AN))
    out["vol"] = vol * 100
    out["mdd"] = float((w / w.cummax() - 1).min() * 100)
    out["dist_52w"] = float((w.iloc[-1] / w.max() - 1) * 100)
    ann = float((w.iloc[-1] / w.iloc[0]) ** (JOURS_AN / max(len(w) - 1, 1)) - 1)
    out["rdt_1a"] = ann * 100
    if vol > 0:
        out["sharpe"] = (ann - rf) / vol
    rf_j = rf / JOURS_AN
    dd = float(np.sqrt(np.mean(np.minimum(r - rf_j, 0.0) ** 2)) * math.sqrt(JOURS_AN))
    if dd > 0:
        out["sortino"] = (ann - rf) / dd
    if n >= 253:
        out["mom_12_1"] = float((c.iloc[-22] / c.iloc[-253] - 1) * 100)   # 12 mois hors dernier mois
    out["beta"] = calculer_beta(c, bench)
    return out
